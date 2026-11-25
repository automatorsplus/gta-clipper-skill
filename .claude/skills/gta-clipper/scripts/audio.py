"""Sound and picture helpers for the clip: the loudness master, the AAC encoder, the size of a video, and the swear
filter for the on-screen words."""
from __future__ import annotations
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E401

import re  # noqa: E402
import subprocess  # noqa: E402

import loudness  # noqa: E402

SR = 48000
MASTER = "acompressor=threshold=-20dB:ratio=4:attack=4:release=150:makeup=6dB"
LIMIT = 0.6        # the limiter's ceiling (-4.4 dBFS): keeps every clip under -1 dBTP after the AAC encode


def _aac() -> str:
    """Apple's AAC encoder when ffmpeg has it (every Mac's ffmpeg from Homebrew): it adds far less true peak."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30)
    return "aac_at" if " aac_at " in r.stdout else "aac"


AAC = _aac()

# on-screen words only: the streamer's own audio is never bleeped
SWEAR = re.compile(r"\b(fuck\w*|shit\w*|bitch\w*|cunt\w*|nigg\w*|fag\w*|retard\w*|whore\w*|slut\w*|pussy|"
                   r"dick\w*|cock\w*|penis\w*|tits?|titties|boobs?|ass|asshole\w*|bastard\w*|wank\w*|twat\w*|"
                   r"porn\w*|cum|horny|motherf\w*)\b", re.I)


def master(wav: str, out: str) -> str:
    """Compress, drive into a limiter, then a measured gain to the target loudness, all before the one AAC encode,
    so the clip sits at the same volume as everything else in the feed."""
    comp = os.path.join(os.path.dirname(out), "comp.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", wav, "-af", MASTER, comp],
                   check=True, timeout=600)
    pre = os.path.join(os.path.dirname(out), "pre.wav")
    drive = 0.0
    for _ in range(4):                         # limiting eats some of the gain; drive again until it lands
        got = loudness.measure(pre if drive else comp)["i"] or -30.0
        if drive and got >= loudness.TARGET_I:
            break
        drive += loudness.TARGET_I + 1.0 - got
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", comp, "-af",
                        "volume=%.2fdB,alimiter=limit=%.3f:attack=2:release=60:level=false" % (drive, LIMIT), pre],
                       check=True, timeout=600)
    got = loudness.measure(pre)["i"]
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", pre, "-af",
                    "aresample=%d,volume=%.2fdB,alimiter=limit=%.3f:attack=2:release=60:level=false,aresample=%d"
                    % (4 * SR, loudness.TARGET_I - got, LIMIT, SR), "-ar", str(SR), out], check=True, timeout=600)
    return out


def probe_size(path: str) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    try:
        w, h = r.stdout.strip().splitlines()[0].split(",")[:2]
        return int(w), int(h)
    except (ValueError, IndexError):
        return 1920, 1080
