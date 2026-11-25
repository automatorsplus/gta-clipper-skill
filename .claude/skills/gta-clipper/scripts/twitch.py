"""Twitch: the most viewed clips of a game, and downloading a clip with the stream around it.

Viewers already clip a stream's best moments, and Twitch lists those clips by views (Helix Get Clips, with your app's
TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET). Each clip says where it sits in the stream's recording, so we download a
little more of the recording around it (the build-up and the reaction), never the whole stream. When the recording is
gone, the clip itself is used.

Without keys, any single clip link still works (Twitch, YouTube, Kick: whatever yt-dlp reads): the clip itself, no
stream around it.
"""
from __future__ import annotations
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E401
import paths  # noqa: E402

import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

API = "https://api.twitch.tv/helix/"
TOKEN = os.path.join(paths.TWITCH_DIR, "token.json")       # the app token (lasts weeks), never the secret
GAMES = {"Grand Theft Auto VI": "1867279146", "Grand Theft Auto V": "32982"}
BEFORE, AFTER = 30.0, 20.0                                 # seconds of the recording kept around the viewers' clip
WINDOW_TIMEOUT = 240


class KeysError(RuntimeError):
    pass


def _ytdlp() -> str:
    mine = os.path.join(os.path.dirname(sys.executable), "yt-dlp")   # the venv's own, kept current by setup.sh
    return mine if os.path.isfile(mine) else "yt-dlp"


def _token() -> str:
    if not paths.has_twitch_keys():
        raise KeysError("no Twitch keys yet. Put TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in %s (see SKILL.md, "
                        "Twitch keys)" % os.path.join(paths.HOME, ".env"))
    try:
        with open(TOKEN) as f:
            t = json.load(f)
        if t["expires"] > time.time() + 3600 and t.get("client") == paths.env("TWITCH_CLIENT_ID"):
            return t["access_token"]
    except (OSError, ValueError, KeyError):
        pass
    body = urllib.parse.urlencode({"client_id": paths.env("TWITCH_CLIENT_ID"),
                                   "client_secret": paths.env("TWITCH_CLIENT_SECRET"),
                                   "grant_type": "client_credentials"}).encode()
    try:
        t = json.load(urllib.request.urlopen(urllib.request.Request("https://id.twitch.tv/oauth2/token", data=body),
                                             timeout=20))
    except urllib.error.HTTPError as e:
        raise KeysError("Twitch turned the keys down (HTTP %d). Check the Client ID and make a New Secret in the "
                        "Twitch developer console, then paste both into .env again" % e.code)
    os.makedirs(paths.TWITCH_DIR, exist_ok=True)
    with open(TOKEN, "w") as f:
        json.dump({"access_token": t["access_token"], "expires": time.time() + t["expires_in"],
                   "client": paths.env("TWITCH_CLIENT_ID")}, f)
    os.chmod(TOKEN, 0o600)
    return t["access_token"]


def get(path: str, **q) -> dict:
    req = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(q, doseq=True),
                                 headers={"Client-Id": paths.env("TWITCH_CLIENT_ID"),
                                          "Authorization": "Bearer " + _token()})
    return json.load(urllib.request.urlopen(req, timeout=20))


def game_id(name: str) -> str:
    got = get("games", name=name)["data"]               # ask Twitch first; the ids above are only a fallback
    if not got and name in GAMES:
        return GAMES[name]
    if not got:
        raise RuntimeError("Twitch has no game called %r (use the exact name from its Twitch page)" % name)
    return got[0]["id"]


def top(game: str = "Grand Theft Auto VI", hours: float = 24, n: int = 20, lang: str | None = "en") -> list[dict]:
    """The most viewed clips of the game made in the last `hours`, most viewed first."""
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, cursor = [], None
    for _ in range(5):                                   # up to 500 clips read to find n in the language
        q = {"game_id": game_id(game), "started_at": start, "first": 100}
        if cursor:
            q["after"] = cursor
        page = get("clips", **q)
        out += [c for c in page["data"] if not lang or (c.get("language") or "").startswith(lang)]
        cursor = (page.get("pagination") or {}).get("cursor")
        if len(out) >= n or not cursor:
            break
    return out[:n]


def clip(ref: str) -> dict:
    """A Twitch clip's details from its link or id (needs keys)."""
    cid = re.sub(r".*/(clip/)?", "", ref.split("?")[0]) if "/" in ref else ref
    got = get("clips", id=cid)["data"]
    if not got:
        raise RuntimeError("Twitch has no clip %r" % ref)
    return got[0]


def is_twitch_clip(ref: str) -> bool:
    return bool(re.search(r"(clips\.twitch\.tv/|twitch\.tv/[^/]+/clip/)", ref))


def _login(broadcaster_id: str) -> str:
    got = get("users", id=broadcaster_id)["data"]
    return got[0]["login"] if got else broadcaster_id


def _seconds(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return float(out or 0)


def _run_group(cmd: list, cwd: str, timeout: int) -> subprocess.CompletedProcess:
    """subprocess.run, but a timeout kills yt-dlp's whole process group (its ffmpeg too)."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate()
        return subprocess.CompletedProcess(cmd, 1, "", "timed out after %d s" % timeout)


def fetch(c: dict, clip_only: bool = False) -> str:
    """The stream around Twitch clip c (from top() or clip()), as a source folder. Returns its id."""
    sid = "tw-" + re.sub(r"[^A-Za-z0-9_-]", "", c["id"])[:60]
    d = os.path.join(paths.SOURCES, sid)
    if os.path.isfile(os.path.join(d, "source.mp4")):
        return sid
    os.makedirs(d, exist_ok=True)
    whole = c.get("video_id") and c.get("vod_offset") is not None and not clip_only
    a = max(0.0, float(c["vod_offset"]) - BEFORE) if whole else 0.0
    b = float(c["vod_offset"]) + float(c["duration"]) + AFTER if whole else None
    # up to 1440p: the webcam is blown up to the full width, so it needs the pixels
    cmd = ["nice", _ytdlp(), "-q", "-f", "best[height<=1440]/best[height<=1080]/best", "--merge-output-format", "mp4",
           "-o", "source.%(ext)s", "--no-playlist", "--retries", "10", "--fragment-retries", "10"]
    if whole:
        r = _run_group(cmd + ["--download-sections", "*%.1f-%.1f" % (a, b), "https://www.twitch.tv/videos/" + c["video_id"]],
                       d, WINDOW_TIMEOUT)
        if r.returncode != 0 or not os.path.isfile(os.path.join(d, "source.mp4")):
            for f in os.listdir(d):                      # the recording refused or hung: the clip itself
                os.remove(os.path.join(d, f))
            whole, a = False, 0.0
    if not whole:
        r = _run_group(cmd + [c["url"]], d, 300)
        if r.returncode != 0 or not os.path.isfile(os.path.join(d, "source.mp4")):
            raise RuntimeError("could not download %s: %s" % (c["url"], (r.stderr or "").strip()[-200:]))
    login = _login(c["broadcaster_id"])
    info = {"title": c["title"], "credit": "twitch.tv/" + login, "who": c["broadcaster_name"],
            "duration": _seconds(os.path.join(d, "source.mp4")), "url": c["url"], "views": c.get("view_count"),
            "clip_at": (float(c["vod_offset"]) - a) if whole else 0.0, "clip_len": float(c["duration"]),
            "whole_recording": bool(whole)}
    with open(os.path.join(d, "source.info.json"), "w") as f:
        json.dump(info, f, indent=1)
    return sid


def fetch_link(url: str) -> str:
    """Any single clip link yt-dlp reads, no keys needed: the clip itself. Returns its source id."""
    sid = "ln-" + hashlib.sha1(url.encode()).hexdigest()[:12]
    d = os.path.join(paths.SOURCES, sid)
    if os.path.isfile(os.path.join(d, "source.mp4")):
        return sid
    os.makedirs(d, exist_ok=True)
    cmd = ["nice", _ytdlp(), "-q", "-f", "bv*[height<=1440]+ba/b[height<=1440]/best", "--merge-output-format", "mp4",
           "-o", "source.%(ext)s", "--no-playlist", "--write-info-json", "--retries", "10", "--fragment-retries", "10"]
    cookies = paths.env("GTA_CLIPPER_COOKIES_BROWSER")
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    r = _run_group(cmd + [url], d, 600)
    if r.returncode != 0 or not os.path.isfile(os.path.join(d, "source.mp4")):
        err = (r.stderr or "").strip()
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        if "not a bot" in err:
            raise RuntimeError("YouTube wants a sign-in before this Mac can download. Add "
                               "GTA_CLIPPER_COOKIES_BROWSER=chrome to .env (or safari, firefox) while logged in there")
        raise RuntimeError("could not download %s: %s" % (url, err[-200:]))
    try:
        with open(os.path.join(d, "source.info.json")) as f:
            y = json.load(f)
    except (OSError, ValueError):
        y = {}
    who = y.get("creator") or y.get("uploader") or y.get("channel") or "the streamer"
    site = (y.get("extractor_key") or "").lower()
    if "twitch" in site:
        # the login is in the link (twitch.tv/<login>/clip/...); yt-dlp's uploader_id is the numeric account id
        m = re.search(r"twitch\.tv/([A-Za-z0-9_]+)/clip/", url)
        login = m.group(1) if m else re.sub(r"[^A-Za-z0-9_]", "", str(who)).lower()
        credit = "twitch.tv/" + login.lower()
    else:
        credit = re.sub(r"^https?://(www\.)?", "", str(y.get("channel_url") or y.get("uploader_url") or who))
    dur = _seconds(os.path.join(d, "source.mp4"))
    info = {"title": y.get("title") or "", "credit": credit, "who": who, "duration": dur, "url": url,
            "views": y.get("view_count"), "clip_at": 0.0, "clip_len": dur, "whole_recording": False}
    with open(os.path.join(d, "source.info.json"), "w") as f:
        json.dump(info, f, indent=1)
    return sid


def show(clips: list[dict]) -> str:
    return "\n".join("%2d. %7d views  %-18.18s %3ds  %s\n      %s" % (
        i, c["view_count"], c["broadcaster_name"], round(c["duration"]), c["title"][:60], c["url"])
        for i, c in enumerate(clips, 1))
