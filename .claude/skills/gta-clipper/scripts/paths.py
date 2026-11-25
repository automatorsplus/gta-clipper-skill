"""Where everything is, and the Twitch keys. Every script imports this first.

Work files go under GTA_CLIPPER_HOME (default: the folder you run from):

    gta-clips/clips/              finished clips (.mp4) and their details (.json)
    gta-clips/sources/<id>/       downloaded streams, transcripts, the webcam box
    gta-clips/_twitch/            the Twitch app token and the list of clips already tried

Twitch keys (TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET) are read from the environment, else from a .env file in
GTA_CLIPPER_HOME. The Whisper model is WHISPER_MODEL, default ~/.cache/whisper/ggml-small.bin (setup.sh fetches it).
"""
from __future__ import annotations

import os
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(SCRIPTS)

HOME = os.path.abspath(os.environ.get("GTA_CLIPPER_HOME") or os.getcwd())
WORK = os.path.join(HOME, "gta-clips")
CLIPS = os.path.join(WORK, "clips")
SOURCES = os.path.join(WORK, "sources")
TWITCH_DIR = os.path.join(WORK, "_twitch")

WHISPER_MODEL = os.path.expanduser(os.environ.get("WHISPER_MODEL") or "~/.cache/whisper/ggml-small.bin")

for _bin in ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin")):
    if os.path.isdir(_bin) and _bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _bin

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def env(name: str) -> str:
    """A setting from the environment, else from GTA_CLIPPER_HOME/.env. '' when it is not set anywhere."""
    if os.environ.get(name):
        return os.environ[name].strip()
    path = os.path.join(HOME, ".env")
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


def has_twitch_keys() -> bool:
    return bool(env("TWITCH_CLIENT_ID") and env("TWITCH_CLIENT_SECRET"))
