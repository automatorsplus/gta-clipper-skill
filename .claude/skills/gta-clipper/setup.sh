#!/usr/bin/env bash
# One-time setup for the GTA clipper. Safe to run again: it skips anything already done.
#   bash .claude/skills/gta-clipper/setup.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL="${WHISPER_MODEL:-$HOME/.cache/whisper/ggml-small.bin}"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This pack is built for macOS (it uses the Mac's system fonts)." >&2
  exit 1
fi

echo "1/4 Command line tools"
if ! command -v brew >/dev/null; then
  echo "  Homebrew is missing. Install it from https://brew.sh then run this again." >&2
  exit 1
fi
for pair in ffmpeg:ffmpeg whisper-cli:whisper-cpp deno:deno; do   # deno: yt-dlp needs it to solve YouTube's challenge
  cmd="${pair%%:*}"; pkg="${pair##*:}"
  if command -v "$cmd" >/dev/null; then echo "  $cmd ok"; else echo "  installing $pkg"; brew install "$pkg"; fi
done

echo "2/4 Python libraries (into $HERE/.venv)"
PYBIN=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)'; then
    PYBIN="$(command -v "$c")"; break
  fi
done
if [[ -z "$PYBIN" ]]; then
  echo "  needs Python 3.10 to 3.13: brew install python@3.12, then run this again" >&2
  exit 1
fi
if [[ -x "$HERE/.venv/bin/python" ]] && ! "$HERE/.venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  rm -rf "$HERE/.venv"            # an old venv on Python 3.9 cannot run a current yt-dlp
fi
[[ -x "$HERE/.venv/bin/python" ]] || "$PYBIN" -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" install -q --upgrade pip
"$HERE/.venv/bin/pip" install -q -U -r "$HERE/requirements.txt"     # -U keeps yt-dlp and its YouTube solver current
echo "  ok"

echo "3/4 Whisper model (466 MB, reads what streamers and players say)"
if [[ -f "$MODEL" ]]; then
  echo "  already at $MODEL"
else
  mkdir -p "$(dirname "$MODEL")"
  curl -L --fail -o "$MODEL.part" "$MODEL_URL" && mv "$MODEL.part" "$MODEL"
  echo "  saved to $MODEL"
fi

echo "4/4 Claude Code"
if command -v claude >/dev/null || [[ -x "$HOME/.local/bin/claude" ]]; then
  echo "  ok (the clipper asks Claude through your logged-in Claude Code, no API key)"
else
  echo "  claude is not on your PATH. Install Claude Code and log in first." >&2
  exit 1
fi

echo
echo "Ready. Next:"
echo "  1. Twitch keys into .env (SKILL.md, Twitch keys), then test:  $HERE/.venv/bin/python $HERE/scripts/clip.py top"
echo "  2. Make clips:  $HERE/.venv/bin/python $HERE/scripts/clip.py auto --n 3"
echo "  No keys yet? Any clip link works:  $HERE/.venv/bin/python $HERE/scripts/clip.py make \"<clip link>\""
