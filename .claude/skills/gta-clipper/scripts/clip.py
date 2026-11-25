#!/usr/bin/env python3
"""Streamer clips: one streamer, one moment, as a vertical clip ready for TikTok, Reels and Shorts.

    clip.py top  [--hours 24] [--n 10] [--game "Grand Theft Auto VI"]     what is most viewed on Twitch right now
    clip.py auto [--n 3] [--hours 24] [--color yellow]                    make clips from the most viewed, one per streamer
    clip.py make <clip link> [<clip link> ...] [--color pink]             make a clip from a link you picked

What a clip is:
  - the streamer's webcam big across the top (Claude finds it; no webcam, no clip), the game below, cropped to the
    middle of the picture, the streamer's name on the seam
  - the loudest few seconds pulled to the front as the hook, then the moment from its build-up to the reaction
  - every word the streamer says, three at a time, the spoken word lit in your colour
  - a short label over the seam during the hook, a YouTube title, and a post caption crediting the streamer
Claude is asked twice per clip, both small calls: is it a moment worth posting (and which part), and where the webcam is.
`top` and `auto` need your Twitch app keys in .env; `make` works on any clip link without them.
"""
from __future__ import annotations
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E401
import paths  # noqa: E402

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import audio  # noqa: E402
import claude_run  # noqa: E402
import facecam  # noqa: E402
import loudness  # noqa: E402
import twitch  # noqa: E402

W, H, FPS = 1080, 1920, 30
CAM_H = 640                      # the webcam band, 0 to 640
GAME_H = 1120                    # the game, 640 to 1760; black below it (where the apps put their buttons)
MIN_S, MAX_S = 12.0, 88.0        # the moment itself
LEAD, TAIL = 6.0, 4.0            # seconds of the stream kept before and after the viewers' clip, when there is a recording
HOOK_S = (2.4, 3.6)
LABEL_AFTER = 4.0                # seconds the label stays once the moment starts
GROUP = 3                        # words on screen at once
MIN_VIEWS = 100                  # a clip fewer people watched than this is not a moment yet
ROUND = "/System/Library/Fonts/SFNSRounded.ttf"
BLACK = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
COLORS = {"yellow": (255, 214, 0), "pink": (255, 40, 200), "cyan": (0, 230, 255), "green": (60, 230, 90),
          "red": (255, 60, 60), "white": (255, 255, 255)}
USED = os.path.join(paths.TWITCH_DIR, "used.json")

ASK = """A streamer's {game} moment is being posted as a short vertical clip: their webcam on top, the game below.
Streamer: {who}. The clip is titled: {title!r}. What is said in it, with the time in seconds:
{said}

Frames of the stream, with their times, are attached: {files}. Open each with Read first.

Answer as JSON only:
{{"right_game": true or false (is the game on screen {game} being played: not another game, not a full-screen webcam),
 "cutscene": true or false (is most of it a cutscene or a scripted story scene the player only watches. A mission the streamer is actually playing, driving, shooting or exploring while characters talk, is NOT a cutscene),
 "chat_in_middle": true or false (is the stream's chat or a big overlay over the middle of the game picture),
 "adult": true or false (nudity, sex, a strip club, a character in underwear as the point of the clip, or a slur said),
 "payoff": true or false (does the thing the moment builds to actually happen on screen or get said; false if it never comes),
 "start": seconds (from the times above) where the clip should start: just before the set-up, cutting any slow lead-in,
 "end": seconds where it should end: about 1 to 2 seconds after the payoff and the streamer's reaction, cutting anything after. The part between start and end must be at least 15 seconds and must not have a stretch of 8 seconds or more where nothing is said and nothing happens; if it cannot avoid one, set usable to false,
 "moment": "one plain sentence: what happens",
 "usable": true or false (true only for a funny, surprising or impressive gameplay moment a stranger would get without context),
 "kind": "fail" (something goes wrong for the player) or "funny" (a joke, a funny reaction or line) or "key" (a discovery, a secret, a big impressive moment) or "meme" (absurd or bizarre: a glitch, strange physics),
 "label": "for fail, funny and key: 2 to 4 words in capitals saying what is happening or about to, as a stage direction, no emoji, e.g. FINDS THE DOG. For meme: a meme caption of up to 7 words in capitals, e.g. WHEN THE NPC HAS PLOT ARMOUR",
 "title": "under 70 characters: a YouTube title naming the streamer as people know them ({who}) and saying what happens, in plain words, ending with at most one emoji; no hashtags, no words in all capitals, no clickbait"}}
No swearing or slurs in label or title."""


def say(text: str) -> None:
    print(text, flush=True)


def _font(path: str, size: int, weight: str | None = None):
    f = ImageFont.truetype(path, size)
    if weight:
        try:
            f.set_variation_by_name(weight)
        except (OSError, ValueError):
            pass
    return f


def _dur(path: str) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True, timeout=60).stdout.strip() or 0)


def words(src_dir: str) -> list[dict]:
    """Every spoken word with its time, [{"a", "b", "w"}], from local Whisper; cached as words.json."""
    out = os.path.join(src_dir, "words.json")
    if os.path.isfile(out):
        with open(out) as f:
            return json.load(f)
    if not shutil.which("whisper-cli") or not os.path.isfile(paths.WHISPER_MODEL):
        raise RuntimeError("Whisper is not set up (run setup.sh): the words on screen need it")
    got = []
    with tempfile.TemporaryDirectory(prefix="words-") as tmp:
        wav = os.path.join(tmp, "a.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", os.path.join(src_dir, "source.mp4"), "-vn", "-ar",
                        "16000", "-ac", "1", wav], check=True, timeout=600)
        subprocess.run(["nice", "whisper-cli", "-m", paths.WHISPER_MODEL, "-f", wav, "-l", "en", "-np", "-oj", "-ml", "1",
                        "-sow", "-of", os.path.join(tmp, "s")], capture_output=True, text=True, timeout=1800, check=True)
        with open(os.path.join(tmp, "s.json"), encoding="utf-8", errors="replace") as f:
            for seg in json.load(f).get("transcription", []):
                t = seg.get("text", "").strip()
                if not t or re.fullmatch(r"[\[\(].*[\]\)]|[^\w]+", t):
                    continue
                a, b = seg["offsets"]["from"] / 1000, seg["offsets"]["to"] / 1000
                if got and not seg.get("text", "").startswith(" ") and a - got[-1]["b"] < 0.05:
                    got[-1]["w"] += t                       # a word Whisper split in two
                    got[-1]["b"] = b
                else:
                    got.append({"a": a, "b": b, "w": t})
    clean = []                                              # the same word many times in a row is Whisper looping
    for g in got:
        if len(clean) >= 4 and all(c["w"].lower() == g["w"].lower() for c in clean[-4:]):
            continue
        clean.append(g)
    with open(out, "w") as f:
        json.dump(clean, f)
    return clean


def loud(src: str) -> np.ndarray:
    """RMS of the sound every 0.1 s."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, timeout=600).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // 800
    return np.sqrt((x[:n * 800].reshape(n, 800) ** 2).mean(axis=1) + 1e-9)


def fetch_twitch(c: dict) -> str:
    """twitch.fetch, but never a silent window: Twitch mutes parts of a recording (music), while the viewers' clip of
    the same moment keeps its sound."""
    sid = twitch.fetch(c)
    d = os.path.join(paths.SOURCES, sid)
    if float(np.median(loud(os.path.join(d, "source.mp4")))) < 0.0008:
        shutil.rmtree(d, ignore_errors=True)
        sid = twitch.fetch(c, clip_only=True)
    return sid


def timeline(info: dict, src: str, ws: list[dict], body: tuple | None = None) -> dict:
    """The hook and the body, in source seconds: the viewers' clip, with a little of the stream either side when the
    recording was there."""
    d = _dur(src)
    ca, cd = float(info.get("clip_at") or 0.0), float(info.get("clip_len") or d)
    b0, b1 = max(0.0, ca - LEAD), min(d, ca + cd + TAIL)
    if body:                                                 # the part the check chose (start and end)
        b0, b1 = max(0.0, body[0]), min(d, body[1])
    if b1 - b0 > MAX_S - HOOK_S[1]:
        b0 = b1 - (MAX_S - HOOK_S[1])
    if b1 - b0 < MIN_S:
        raise RuntimeError("the moment is only %.0f s, too short for a clip" % (b1 - b0))
    r = loud(src)                                            # the hook: the loudest moment, not in the first 5 s
    lo, hi = int(max(ca, b0 + 5.0) * 10), int(min(ca + cd, b1 - 1.0) * 10)
    if hi - lo < 20:
        lo, hi = int((b0 + 5.0) * 10), int((b1 - 1.0) * 10)
    if hi - lo < 10:
        lo, hi = int(b0 * 10), int(b1 * 10)
    k = np.convolve(r, np.ones(15) / 15, mode="same")
    peak = (lo + int(np.argmax(k[lo:hi]))) / 10
    h0 = peak - 1.2
    near = [w for w in ws if h0 - 1.0 <= w["a"] <= peak]
    for i, w in enumerate(near):                             # start on a word that follows a breath
        prev = near[i - 1]["b"] if i else -9
        if w["a"] - prev >= 0.25:
            h0 = w["a"] - 0.08
            break
    ends = [w["b"] for w in ws if h0 + HOOK_S[0] <= w["b"] <= h0 + HOOK_S[1]]
    h1 = (ends[-1] + 0.12) if ends else h0 + 2.8
    h0, h1 = max(b0, h0), min(b1, h1)
    return {"hook": [round(h0, 2), round(h1, 2)], "body": [round(b0, 2), round(b1, 2)], "peak": peak}


def crops(box, sw: int, sh: int) -> tuple[tuple, tuple]:
    """(webcam crop, game crop) as x, y, w, h in source pixels."""
    l, t, r, b = box[0] * sw, box[1] * sh, box[2] * sw, box[3] * sh
    bw, bh, asp = r - l, b - t, W / CAM_H
    if bw / bh > asp:                                        # wider than the band: trim the sides
        cw, ch = bh * asp, bh
        cx, cy = l + (bw - cw) / 2, t
    elif bw / bh >= asp * 0.8:                               # a little taller: trim the bottom mostly (keep the head)
        cw, ch = bw, bw / asp
        cx, cy = l, t + (bh - ch) * 0.15
    else:                                                    # a narrow webcam: all of it, on a blurred copy of itself
        cw, ch, cx, cy = bw, bh, l, t
    cam = (int(cx) // 2 * 2, int(cy) // 2 * 2, int(cw) // 2 * 2, int(ch) // 2 * 2)
    gw = int(sh * W / GAME_H) // 2 * 2
    gx = (sw - gw) / 2
    if (l + r) / 2 < sw / 2 and r > gx:                      # webcam on the left: slide the game crop right, off it
        gx = min(sw - gw, r, gx + sw * 0.14)
    elif (l + r) / 2 >= sw / 2 and l < gx + gw:
        gx = max(0, l - gw, gx - sw * 0.14)
    return cam, (int(gx) // 2 * 2, 0, gw, sh)


def _stroke(d, xy, text, font, fill, width):
    d.text(xy, text, font=font, fill=fill, stroke_width=width, stroke_fill=(0, 0, 0, 255))


def caption_image(group: list[str], lit: int, accent: tuple, size: int = 78) -> Image.Image:
    """Up to three words, capitals, white with a black edge, the spoken word in your colour."""
    font = _font(ROUND, size, "Black")
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    gap = int(size * 0.3)
    wd = [probe.textlength(w, font=font) for w in group]
    lines, cur, cw = [], [], 0.0
    for i, w in enumerate(group):
        if cur and cw + gap + wd[i] > 940:
            lines.append(cur)
            cur, cw = [], 0.0
        cw += (gap if cur else 0) + wd[i]
        cur.append(i)
    lines.append(cur)
    lh = int(size * 1.12)
    img = Image.new("RGBA", (W, lh * len(lines) + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for n, ln in enumerate(lines):
        tot = sum(wd[i] for i in ln) + gap * (len(ln) - 1)
        x = (W - tot) / 2
        for i in ln:
            _stroke(d, (x, 10 + n * lh), group[i], font, accent + (255,) if i == lit else (255, 255, 255, 255), 9)
            x += wd[i] + gap
    return img


def label_image(text: str, stars: bool = True) -> Image.Image:
    """The label over the seam: white Arial Black with a black edge and shadow; two lines when one would not fit."""
    text = text.strip("* ").upper()
    text = "*" + text + "*" if stars else text
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    ws = text.split()
    best = None
    for size in range(100, 43, -4):
        font = _font(BLACK, size)
        if probe.textlength(text, font=font) <= 980:
            best = (size, [text])
            break
        if size <= 76 and len(ws) > 2:
            cuts = [(" ".join(ws[:k]), " ".join(ws[k:])) for k in range(1, len(ws))]
            a, b = min(cuts, key=lambda c: abs(probe.textlength(c[0], font=font) - probe.textlength(c[1], font=font)))
            if max(probe.textlength(a, font=font), probe.textlength(b, font=font)) <= 980:
                best = (size, [a, b])
                break
    size, lines = best or (44, [text])
    font = _font(BLACK, size)
    lh = int(size * 1.08)
    img = Image.new("RGBA", (W, lh * len(lines) + 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for n, ln in enumerate(lines):
        tw = d.textlength(ln, font=font)
        y = 20 + n * lh
        d.text(((W - tw) / 2 + 6, y + 6), ln, font=font, fill=(0, 0, 0, 255), stroke_width=6, stroke_fill=(0, 0, 0, 255))
        d.text(((W - tw) / 2, y), ln, font=font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    return img


def tag_image(name: str, accent: tuple) -> Image.Image:
    """The streamer's credit on the seam: a black plate edged in your colour."""
    font = _font(ROUND, 36, "Bold")
    tw = int(ImageDraw.Draw(Image.new("RGBA", (8, 8))).textlength(name, font=font))
    img = Image.new("RGBA", (tw + 64, 62), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, img.width - 1, 61), radius=12, fill=(0, 0, 0, 255), outline=accent + (255,), width=4)
    d.text((32, 8), name, font=font, fill=(255, 255, 255, 255))
    return img


def caption_events(ws: list[dict], tl: dict) -> list[dict]:
    """[{"t0", "t1", "group", "lit"}] in the clip's own seconds, for the hook then the body."""
    out = []
    h0, h1 = tl["hook"]
    b0, b1 = tl["body"]
    for (a, b, shift) in ((h0, h1, -h0), (b0, b1, (h1 - h0) - b0)):
        seg = [w for w in ws if w["a"] >= a - 0.05 and w["b"] <= b + 0.3]
        groups, cur = [], []
        for w in seg:
            if cur and (len(cur) >= GROUP or w["a"] - cur[-1]["b"] > 0.6 or re.search(r"[.!?]$", cur[-1]["w"])):
                groups.append(cur)
                cur = []
            cur.append(w)
        if cur:
            groups.append(cur)
        for gi, g in enumerate(groups):
            text = [re.sub(r"^[^\w*']+|[^\w*'?!]+$", "",
                           audio.SWEAR.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), w["w"])).upper()
                    for w in g]
            nxt = groups[gi + 1][0]["a"] if gi + 1 < len(groups) else b
            for i, w in enumerate(g):
                # Whisper stretches a line's last word across the silence after it
                t1 = min(g[i + 1]["a"], w["a"] + 1.2) if i + 1 < len(g) else min(w["b"] + 0.35, w["a"] + 1.2, nxt)
                if text[i]:
                    out.append({"t0": max(a, w["a"]) + shift, "t1": min(b, max(t1, w["a"] + 0.08)) + shift,
                                "group": [t or "" for t in text], "lit": i})
    return out


def _paste(frame: np.ndarray, img: np.ndarray, x: int, y: int) -> None:
    h, w = img.shape[:2]
    a = img[:, :, 3:4].astype(np.float32) / 255
    reg = frame[y:y + h, x:x + w].astype(np.float32)
    frame[y:y + h, x:x + w] = (reg * (1 - a) + img[:, :, :3].astype(np.float32) * a).astype(np.uint8)


def check(info: dict, src: str, tl: dict, ws: list, game: str) -> dict:
    """One Claude call: is it a moment worth a clip, which part to keep, its kind, label and title."""
    b0, b1 = tl["body"]
    lines, cur = [], []
    for w in ws:
        if not b0 <= w["a"] <= b1:
            continue
        if cur and (w["a"] - cur[-1]["b"] > 0.7 or len(cur) >= 12):
            lines.append("[%.1f] %s" % (cur[0]["a"] - b0, " ".join(x["w"] for x in cur)))
            cur = []
        cur.append(w)
    if cur:
        lines.append("[%.1f] %s" % (cur[0]["a"] - b0, " ".join(x["w"] for x in cur)))
    said = "\n".join(lines) or "(nothing said)"
    with tempfile.TemporaryDirectory(prefix="check-") as tmp:
        files, named = {}, []
        n = 8
        for k in range(n):
            at = (b1 - b0) * (0.03 + 0.94 * k / (n - 1))
            p = os.path.join(tmp, "f%d.jpg" % (k + 1))
            subprocess.run(["ffmpeg", "-v", "fatal", "-ss", "%.2f" % (b0 + at), "-i", src, "-frames:v", "1",
                            "-vf", "scale=768:-2", "-y", p], timeout=60, check=True)
            files[os.path.basename(p)] = p
            named.append("%s at %.1f s" % (os.path.basename(p), at))
        got = claude_run.ask_json(ASK.format(game=game, who=info["who"], title=info["title"], said=said[:4000],
                                             files=", ".join(named)), timeout=600, files=files)
    try:                                                     # start and end back into source seconds
        a, b = float(got.get("start")), float(got.get("end"))
        if b - a >= MIN_S:
            got["part"] = [round(b0 + max(0.0, a), 2), round(b0 + min(b1 - b0, b), 2)]
    except (TypeError, ValueError):
        pass
    return got


def refused(text: dict) -> str | None:
    for key, bad, why in (("right_game", False, "not the right game"), ("cutscene", True, "a story cutscene"),
                          ("chat_in_middle", True, "chat over the game"), ("adult", True, "adult content or a slur"),
                          ("payoff", False, "it ends before the payoff"),
                          ("usable", False, "not a moment worth a clip")):
        if key in text and bool(text[key]) is bad:
            return why
    return None


def render(sid: str, accent: tuple, game: str) -> str:
    """Make the clip for one downloaded source. Returns the clip's path; raises RuntimeError with the reason when the
    source is not clip material."""
    d = os.path.join(paths.SOURCES, sid)
    src = os.path.join(d, "source.mp4")
    with open(os.path.join(d, "source.info.json")) as f:
        info = json.load(f)
    say("  Reading what %s says (Whisper)" % info["who"])
    ws = words(d)
    tl = timeline(info, src, ws)
    say("  Claude is checking the moment")
    text = check(info, src, tl, ws, game)
    why = refused(text)
    if why:
        raise RuntimeError("skipped: %s (%s)" % (why, text.get("moment") or info["title"]))
    say("  Claude is finding the webcam")
    box = facecam.find(sid)                                 # after the check: a refused clip costs one call, not two
    if not box:
        raise RuntimeError("skipped: no webcam on this stream (the look needs the streamer on top)")
    if text.get("part"):
        tl = timeline(info, src, ws, body=tuple(text["part"]))
    (h0, h1), (b0, b1) = tl["hook"], tl["body"]
    frames = int(round((h1 - h0) * FPS)) + int(round((b1 - b0) * FPS))
    kind = text.get("kind") or "key"
    login = info["credit"].split("/")[-1].lstrip("@")
    plan = {"kind": kind, "views": info.get("views"), "streamer": login, "credit": info["credit"],
            "label": text.get("label"), "title": text.get("title"), "moment": text.get("moment"),
            "post_caption": "%s 🎮 via %s" % (text.get("moment") or info["title"], info["credit"]),
            "url": info.get("url"), "timeline": tl, "cam_box": box, "accent": list(accent)}
    name = "%s-%s-%d-%s" % (re.sub(r"[^a-z0-9]", "", login.lower())[:24] or "clip", kind, int(b0),
                            hashlib.sha1(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:6])
    os.makedirs(paths.CLIPS, exist_ok=True)
    final = os.path.join(paths.CLIPS, name + ".mp4")
    if os.path.isfile(final):
        return final
    say("  Rendering (%.0f s clip)" % (frames / FPS))
    sw, sh = audio.probe_size(src)
    cam, game_crop = crops(box, sw, sh)
    if cam[2] / cam[3] < (W / CAM_H) * 0.8:                  # narrow webcam: whole, centred, on a blurred fill
        camf = ("[c]crop=%d:%d:%d:%d,split[cb][cf];[cb]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
                "boxblur=24:2,eq=brightness=-0.08[cbg];[cf]scale=-2:%d:flags=lanczos,unsharp=5:5:0.6[cfg];"
                "[cbg][cfg]overlay=(W-w)/2:0[c2];" % (cam[2], cam[3], cam[0], cam[1], W, CAM_H, W, CAM_H, CAM_H))
    else:
        camf = "[c]crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos,unsharp=5:5:0.6[c2];" % (cam[2], cam[3], cam[0], cam[1],
                                                                                      W, CAM_H)
    cut = (("[0:v]trim=%.3f:%.3f,setpts=PTS-STARTPTS[h];[0:v]trim=%.3f:%.3f,setpts=PTS-STARTPTS[b];"
            "[h][b]concat=n=2:v=1:a=0,fps=%d,split[c][g];" % (h0, h1, b0, b1, FPS)) + camf +
           ("[g]crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos,unsharp=5:5:0.4[g2];"
            "[c2][g2]vstack,pad=%d:%d:0:0:black[v]" % (game_crop[2], game_crop[3], game_crop[0], game_crop[1],
                                                       W, GAME_H, W, H)))
    events = caption_events(ws, tl)
    cache = {}
    label = np.asarray(label_image(text.get("label") or "WATCH THIS", stars=kind != "meme"))
    tag = np.asarray(tag_image(info["credit"], accent))
    label_until = (h1 - h0) + LABEL_AFTER
    with tempfile.TemporaryDirectory(prefix="render-") as tmp:
        vid = os.path.join(tmp, "v.mp4")
        dec = subprocess.Popen(["ffmpeg", "-v", "fatal", "-i", src, "-filter_complex", cut, "-map", "[v]", "-f",
                                "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                                "%dx%d" % (W, H), "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                                "-crf", "20", "-pix_fmt", "yuv420p", vid], stdin=subprocess.PIPE)
        n, ei = 0, 0
        while n < frames:
            raw = dec.stdout.read(W * H * 3)
            if len(raw) < W * H * 3:
                break
            fr = np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3).copy()
            t = n / FPS
            fr[CAM_H - 3:CAM_H + 3] = accent                 # your colour on the seam and under the game
            fr[CAM_H + GAME_H:CAM_H + GAME_H + 6] = accent
            if t < label_until:
                _paste(fr, label, 0, CAM_H - label.shape[0] + 34)
                _paste(fr, tag, (W - tag.shape[1]) // 2, CAM_H + 44)
            else:
                _paste(fr, tag, (W - tag.shape[1]) // 2, CAM_H + 14)
            while ei < len(events) and events[ei]["t1"] <= t:
                ei += 1
            if ei < len(events) and events[ei]["t0"] <= t:
                e = events[ei]
                key = (tuple(e["group"]), e["lit"])
                if key not in cache:
                    cache[key] = np.asarray(caption_image(e["group"], e["lit"], accent))
                _paste(fr, cache[key], 0, CAM_H + 120)
            enc.stdin.write(fr.tobytes())
            n += 1
        dec.stdout.close()
        dec.kill()
        enc.stdin.close()
        if enc.wait():
            raise RuntimeError("the video encode failed")
        wav = os.path.join(tmp, "a.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex",
                        "[0:a]atrim=%.3f:%.3f,asetpts=PTS-STARTPTS[h];[0:a]atrim=%.3f:%.3f,asetpts=PTS-STARTPTS[b];"
                        "[h][b]concat=n=2:v=0:a=1[a]" % (h0, h1, b0, b1), "-map", "[a]", "-ac", "2",
                        "-ar", str(audio.SR), wav], check=True, timeout=600)
        mastered = audio.master(wav, os.path.join(tmp, "m.wav"))
        partial = os.path.join(tmp, "out.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", vid, "-i", mastered, "-c:v", "copy", "-af", "apad",
                        "-c:a", audio.AAC, "-b:a", "192k", "-shortest", "-movflags", "+faststart", partial],
                       check=True, timeout=600)
        shutil.move(partial, final)
    secs = n / FPS
    lv = loudness.measure(final)
    result = {"plan": plan, "duration": round(secs, 2), "frames": n, "words": len(events),
              "crops": {"cam": cam, "game": game_crop}, "loudness": lv,
              "checks": {"length_15_90": 15.0 <= secs <= 90.0, "words_on_screen": len(events) >= 8,
                         "webcam_sharp_enough": min(cam[2], cam[3]) >= 200,
                         "has_sound": (lv.get("i") or -70) > -30}}
    with open(os.path.join(paths.CLIPS, name + ".json"), "w") as f:
        json.dump(result, f, indent=1)
    return final


def _used() -> dict:
    try:
        with open(USED) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_used(u: dict) -> None:
    os.makedirs(paths.TWITCH_DIR, exist_ok=True)
    with open(USED, "w") as f:
        json.dump(u, f, indent=1)


def _color(name: str) -> tuple:
    if name.lower() in COLORS:
        return COLORS[name.lower()]
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", name)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    raise SystemExit("unknown colour %r: use %s, or a hex code like #ff8800" % (name, ", ".join(COLORS)))


def _done(made: list[str], t0: float) -> None:
    say("\nFinished in %s: %d clip(s)" % (time.strftime("%M:%S", time.gmtime(time.time() - t0)), len(made)))
    for p in made:
        say("  " + p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["top", "auto", "make"])
    ap.add_argument("links", nargs="*", help="for make: one or more clip links")
    ap.add_argument("--game", default="Grand Theft Auto VI", help="the game's exact name on Twitch")
    ap.add_argument("--hours", type=float, default=24, help="how far back to look on Twitch")
    ap.add_argument("--n", type=int, default=None, help="top: how many to list (10); auto: how many clips to make (3)")
    ap.add_argument("--color", default="yellow", help="the accent colour: %s, or a hex code" % ", ".join(COLORS))
    ap.add_argument("--lang", default="en", help="clip language on Twitch, '' for any")
    a = ap.parse_args()
    accent = _color(a.color)
    game_short = "GTA 6" if a.game == "Grand Theft Auto VI" else a.game
    t0 = time.time()
    try:
        if a.what == "top":
            clips = twitch.top(a.game, a.hours, a.n or 10, a.lang or None)
            say(twitch.show(clips) if clips else "No %s clips on Twitch in the last %g hours." % (a.game, a.hours))
            return 0
        if a.what == "make":
            if not a.links:
                ap.error("make needs at least one clip link")
            made = []
            for k, link in enumerate(a.links, 1):
                say("[%d/%d] %s" % (k, len(a.links), link))
                try:
                    if twitch.is_twitch_clip(link) and paths.has_twitch_keys():
                        say("  Downloading the clip with the stream around it")
                        sid = fetch_twitch(twitch.clip(link))
                    else:
                        say("  Downloading the clip")
                        sid = twitch.fetch_link(link)
                    made.append(render(sid, accent, game_short))
                    say("  Done: " + made[-1])
                except RuntimeError as e:
                    say("  %s" % e)
            _done(made, t0)
            return 0 if made else 1
        # auto: down the most viewed clips, one per streamer, never one tried before, until n are made
        want = a.n or 3
        say("Looking up the most viewed %s clips of the last %g hours" % (game_short, a.hours))
        clips = twitch.top(a.game, a.hours, 60, a.lang or None)
        used, made, seen, tried = _used(), [], set(), 0
        for c in clips:
            if len(made) >= want or tried >= want * 4:
                break
            who = c["broadcaster_name"].lower()
            if c["id"] in used or who in seen or c["duration"] < 15 or c["view_count"] < MIN_VIEWS:
                continue
            tried += 1
            seen.add(who)
            say("\n[%d of %d made] %s, %d views: %s" % (len(made), want, c["broadcaster_name"], c["view_count"],
                                                      c["title"][:60]))
            sid = None
            try:
                say("  Downloading the clip with the stream around it")
                sid = fetch_twitch(c)
                made.append(render(sid, accent, game_short))
                used[c["id"]] = "made"
                say("  Done: " + made[-1])
            except RuntimeError as e:
                used[c["id"]] = str(e)[:200]
                say("  %s" % e)
            _save_used(used)
            if sid:                                          # the download is large; the clip and its details stay
                shutil.rmtree(os.path.join(paths.SOURCES, sid), ignore_errors=True)
        if not clips:
            say("No %s clips on Twitch in the last %g hours. Try --hours 48." % (game_short, a.hours))
        _done(made, t0)
        return 0 if made else 1
    except twitch.KeysError as e:
        raise SystemExit("\nStopped: %s" % e)
    except (RuntimeError, claude_run.ClaudeError, OSError) as e:
        raise SystemExit("\nStopped: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
