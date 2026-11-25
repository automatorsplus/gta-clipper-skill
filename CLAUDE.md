# GTA Clipper

This repo contains a Claude Code skill for use in any project.

## Skill

- `.claude/skills/gta-clipper/SKILL.md` -- the main skill: setup, the Twitch keys walkthrough, making clips, checking them
- `.claude/skills/gta-clipper/setup.sh` -- one-time setup (ffmpeg, whisper-cpp, Deno, the Python venv, the Whisper model)
- `.claude/skills/gta-clipper/scripts/clip.py` -- run this: `top`, `auto`, `make`
- `.claude/skills/gta-clipper/scripts/` -- the rest of the engine (Twitch, the webcam finder, audio)

Twitch keys go in `.env` (copy `.env.example`); never commit it. Clips go in `gta-clips/clips/`.

See `README.md` for installation, prerequisites, and example prompts.
