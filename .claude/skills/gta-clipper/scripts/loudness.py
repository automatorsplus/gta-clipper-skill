"""Measure and fix delivery loudness, so a clip is never quieter than the video before it in the feed.

  measure()   what a file actually is
  normalise() one pass to spec, video stream copied, audio re-encoded
  gate()      raises unless the file is within tolerance

    python3 loudness.py <clip.mp4> ...          # measure
    python3 loudness.py <clip.mp4> --fix        # normalise in place
"""
from __future__ import annotations

import json
import os
import re
import subprocess

# The delivery target for Shorts, Reels and TikTok. Same number for long-form: both are
# watched next to other people's videos, and being quieter than the video before you is
# the one mixing error a viewer reacts to by leaving.
TARGET_I = -13.8      # LUFS integrated
TARGET_TP = -1.0      # dBTP true peak ceiling
TARGET_LRA = 11.0     # loudness range
TOLERANCE = 1.0       # LU either side of TARGET_I that still counts as on spec


def measure(path: str) -> dict:
    """Integrated loudness, true peak and range of a file, via ffmpeg's ebur128."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
         "-af", "ebur128=framelog=quiet:peak=true", "-f", "null", "-"],
        capture_output=True, text=True, timeout=3600,
    )
    out = r.stderr
    def grab(label, unit):
        m = re.search(label + r":\s*(-?\d+(?:\.\d+)?)\s*" + unit, out)
        return float(m.group(1)) if m else None
    return {
        "i": grab("I", "LUFS"),
        "lra": grab("LRA", "LU"),
        "tp": grab("Peak", "dBFS"),
    }


def normalise(path: str, out_path: str | None = None) -> str:
    """Two-pass loudnorm to spec. Video is stream-copied; only audio is re-encoded.

    Two-pass rather than one, because a single-pass loudnorm on a 30 minute ambient bed
    with a wide loudness range guesses from the first few seconds and lands several LU
    off. The first pass measures, the second corrects with those measurements.
    """
    path = str(path)
    out_path = str(out_path or path)

    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn",
         "-af", f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=3600,
    ).stderr
    blob = probe[probe.rindex("{"):probe.rindex("}") + 1]
    m = json.loads(blob)

    af = (
        f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}"
        f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
        f":offset={m['target_offset']}:linear=true:print_format=summary"
    )
    tmp = out_path + ".loudnorm.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", path,
         "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
         "-af", af, "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", tmp],
        check=True, timeout=7200,
    )
    os.replace(tmp, out_path)

    # 🔴 loudnorm can still land off target. `linear=true` silently falls back to dynamic
    # mode when the gain it needs would breach the true-peak ceiling, and on this material
    # that left files anywhere from -12.0 to -14.8 after a pass that asked for -13.8.
    # Measured 2026-09-03 across 129 masters: four were more than 1 LU out afterwards.
    # A straight gain correction is exact, cheap, and cannot overshoot, so it finishes the
    # job. Only ever applied downward-or-small, and only once.
    got = measure(out_path)
    if got["i"] is not None and abs(got["i"] - TARGET_I) > 0.3:
        delta = TARGET_I - got["i"]
        peak = got["tp"] if got["tp"] is not None else -1.0
        if peak + delta > TARGET_TP:          # would clip; pull back to the ceiling
            delta = TARGET_TP - peak
        if abs(delta) > 0.05:
            tmp2 = out_path + ".gain.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", out_path,
                 "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                 "-af", f"volume={delta:+.2f}dB", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", tmp2],
                check=True, timeout=7200,
            )
            os.replace(tmp2, out_path)

    # 🔴 THIRD STAGE, FOR MATERIAL A FLAT GAIN CANNOT REACH. Found 2026-09-04 on the
    # long-form parts: eight of forty sat 1.1-2.7 LU under target with true peaks already
    # at -0.5 to -1.0 dBTP. Raising them needs +2.7 dB, which would put the peak at +1.9,
    # so the gain trim above correctly clamps to the ceiling and the file stays quiet.
    # That is not a bug in the trim: a high crest factor cannot be fixed by gain at all.
    #
    # It needs COMPRESSION, which is precisely what loudnorm's dynamic mode does and what
    # `linear=true` above forbids. So when the linear path lands short, re-run dynamic.
    # Its whole job is to hit the integrated target under a true-peak ceiling by reshaping
    # the envelope, and on this material it does, without touching the video.
    #
    # Ordered this way deliberately: linear first because it preserves dynamics exactly and
    # is right for most clips, dynamic only for the ones linear provably cannot serve.
    got = measure(out_path)
    if got["i"] is not None and abs(got["i"] - TARGET_I) > TOLERANCE:
        tmp3 = out_path + ".dyn.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", out_path,
             "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
             "-af", f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp3],
            check=True, timeout=7200,
        )
        os.replace(tmp3, out_path)
    return out_path


def gate(path: str, tolerance: float = TOLERANCE) -> dict:
    """Raise unless `path` is within tolerance of the target. Returns the measurement."""
    m = measure(path)
    if m["i"] is None:
        raise SystemExit(
            f"LOUDNESS GATE: no audio measurement from {os.path.basename(path)}. "
            "A silent or missing audio stream is a defect, not a pass."
        )
    if abs(m["i"] - TARGET_I) > tolerance:
        raise SystemExit(
            f"LOUDNESS GATE FAILED: {os.path.basename(path)} is {m['i']:.1f} LUFS, "
            f"target {TARGET_I} +/- {tolerance}. Fix it with:\n"
            f"  python3 -c \"import loudness; loudness.normalise('{path}')\"\n"
            "This is the check that was missing when two 30-minute videos shipped at "
            "-17.6 LUFS on 2026-09-03."
        )
    return m


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Measure or fix delivery loudness.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--fix", action="store_true", help="normalise in place to spec")
    a = ap.parse_args()
    for f in a.files:
        before = measure(f)
        if a.fix:
            normalise(f)
            after = measure(f)
            print("%-50s %.1f -> %.1f LUFS" % (os.path.basename(f), before["i"], after["i"]))
        else:
            ok = before["i"] is not None and abs(before["i"] - TARGET_I) <= TOLERANCE
            print("%-50s %6s LUFS  TP %5s  LRA %5s  %s" % (
                os.path.basename(f), before["i"], before["tp"], before["lra"],
                "on spec" if ok else "OFF SPEC (--fix)"))
