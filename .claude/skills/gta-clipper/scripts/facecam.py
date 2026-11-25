"""Where the streamer's webcam sits in the picture, so it can go big on top of the clip.

Claude reads two frames of the stream with a 10% grid drawn on and gives the webcam's box, or none. (Face finders
miss webcams with borders and mistake game characters for faces; Claude reading a gridded frame does not.) Cached as
facecam.json in the source folder: {"box": [left, top, right, bottom] as fractions of the frame} or {"box": null}.
"""
from __future__ import annotations
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E401
import paths  # noqa: E402

import json  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

import claude_run  # noqa: E402

GRID = (255, 230, 0)
ASK = """Each image is a frame from a stream, with a yellow grid every 10 percent (labels are percent of width along
the top and percent of height down the left). Two frames per stream, named <stream>-1.jpg and <stream>-2.jpg: {files}.
For each stream, is there a webcam overlay showing the real streamer (a real person on camera, not a game character)?
If yes, give the tightest box around the whole webcam area as percent of the frame: [left, top, right, bottom], read
carefully against the grid lines, using both frames. If the webcam has no border (a cut-out person), box the person's
head and shoulders. Open every image with Read first.
Answer JSON only: {{"streams": [{{"name": "<stream>", "webcam": true, "box": [l, t, r, b]}}]}}"""


def _frame(path: str, at: float, out: str) -> None:
    subprocess.run(["ffmpeg", "-v", "fatal", "-ss", "%.2f" % at, "-i", path, "-frames:v", "1", "-vf", "scale=960:-2",
                    "-y", out], timeout=60, check=True)
    img = Image.open(out).convert("RGB")
    d = ImageDraw.Draw(img)
    w, h = img.size
    for i in range(1, 10):
        x, y = int(w * i / 10), int(h * i / 10)
        d.line((x, 0, x, h), fill=GRID, width=1)
        d.line((0, y, w, y), fill=GRID, width=1)
        d.text((x + 3, 2), str(i * 10), fill=GRID)
        d.text((3, y - 12), str(i * 10), fill=GRID)
    img.save(out, quality=88)


def find(sid: str):
    """The webcam box for one source (fractions), or None when there is no webcam. One small Claude call, cached."""
    d = os.path.join(paths.SOURCES, sid)
    cache = os.path.join(d, "facecam.json")
    try:
        with open(cache) as f:
            return json.load(f)["box"]
    except (OSError, KeyError, ValueError):
        pass
    src = os.path.join(d, "source.mp4")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                               capture_output=True, text=True, timeout=60).stdout.strip() or 0)
    with tempfile.TemporaryDirectory(prefix="cam-") as tmp:
        files = {}
        for k, frac in ((1, 0.3), (2, 0.7)):
            p = os.path.join(tmp, "s01-%d.jpg" % k)
            _frame(src, dur * frac, p)
            files[os.path.basename(p)] = p
        got = claude_run.ask_json(ASK.format(files=", ".join(sorted(files))), timeout=600, files=files)
    s = next((x for x in got.get("streams", []) if str(x.get("name")) == "s01"), None) or \
        (got.get("streams") or [{}])[0]
    box = None
    try:
        if s.get("webcam") and s.get("box"):
            l, t, r, b = [min(max(float(v) / 100, 0.0), 1.0) for v in s["box"]]
            if r - l > 0.05 and b - t > 0.05:
                box = [round(l, 4), round(t, 4), round(r, 4), round(b, 4)]
    except (TypeError, ValueError):
        box = None
    with open(cache, "w") as f:
        json.dump({"box": box}, f)
    return box
