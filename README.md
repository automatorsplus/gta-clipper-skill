# GTA Clipper Skill for Claude Code

> Part of the **Automators+** skills library -- Claude Code skills shared with the [Automators community](https://www.skool.com/automation-forge-7306/about).

Every day, streamers' best GTA 6 moments get clipped by their viewers on Twitch. This skill finds the most viewed ones, and turns each into a finished vertical clip ready for TikTok, Reels and Shorts: the streamer's webcam big on top, the game below, every word they say popping up as they say it, the funniest second pulled to the front as the hook, and the streamer credited on screen.

You run one command. Claude checks every moment is worth posting before it renders anything.

## What You Get

- A drop-in Claude Code skill at `.claude/skills/gta-clipper/`
- **Finds what's hot:** the most viewed GTA 6 clips on Twitch from the last day, straight from Twitch's own API
- **The build-up and the reaction:** it downloads the stream around each clip, not just the clip
- **Claude checks every moment first:** real gameplay, not a cutscene, no chat over the game, nothing adult, and it actually pays off. It also trims the slow start
- **Webcam on top, game below:** Claude finds the streamer's webcam wherever it sits on their stream
- **Word-by-word captions** from local Whisper, the spoken word lit in your colour
- **The hook up front:** the loudest moment plays first, then the clip from its build-up
- A YouTube title and a post caption crediting the streamer, for every clip
- **No paid API:** a free Twitch app and your own Claude Code

## Install the Skill

### Option 1: URL install

```
claude skill add --url https://raw.githubusercontent.com/automatorsplus/gta-clipper-skill/main/.claude/skills/gta-clipper/SKILL.md
```

Then clone the repo too: the skill runs the scripts that sit beside `SKILL.md`.

### Option 2: Manual copy

Copy `.claude/skills/gta-clipper/` into your project's `.claude/skills/` folder.

## Prerequisites

- **A Mac.** The captions use macOS system fonts
- **Claude Code**, logged in
- **Homebrew** ([brew.sh](https://brew.sh))
- **A Twitch account with two-factor authentication on**, for the free API keys

Run the setup once. It installs what's missing, builds a Python environment inside the skill folder and downloads the small Whisper model (466 MB):

```bash
bash .claude/skills/gta-clipper/setup.sh
```

Then get your Twitch keys, free, about five minutes. Claude walks you through it (it's in `SKILL.md`): register an app at [dev.twitch.tv/console](https://dev.twitch.tv/console), copy the Client ID and a New Secret into `.env`.

## Try It

- `Set up my Twitch keys for the GTA clipper`
- `What are the most viewed GTA 6 clips on Twitch today?`
- `Make me 3 streamer clips from today's top GTA 6 moments`
- `Make a clip from this one in pink: <twitch clip link>`

Clips land in `gta-clips/clips/`, each with a `.json` holding its title and post caption. Claude watches every finished clip before calling it done.

## No Keys Yet?

Paste any clip link (Twitch, YouTube, Kick) and it makes the clip from that alone. The keys add the automatic top-clips search and the stream around each clip.

## Play It Safe

The streamer's name is on screen the whole clip and in the post caption. If a streamer asks you to take a clip down, do it straight away. No story spoilers, and no GTA or Rockstar branding in your page's name or logo.

## What It Costs

Nothing beyond your Claude plan: two small Claude calls per clip on your own account. Twitch's API is free. Everything else runs on your Mac.
