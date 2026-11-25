---
name: gta-clipper
description: Turn streamers' GTA 6 moments on Twitch into finished vertical clips for TikTok, Reels and Shorts. Finds the most viewed clips on Twitch (with the user's free Twitch app keys), downloads each with the stream around it, has Claude check it is a real moment and trim it, finds the streamer's webcam, and renders a 9:16 clip with the webcam big on top, the game below, every word the streamer says lit up word by word, the loudest moment pulled to the front as the hook, and the streamer credited on screen. Also works on any single clip link without keys. Use when asked to clip streamers, make GTA 6 clips, turn Twitch clips into shorts, start a clip page, or set up the Twitch keys for clipping.
---

# GTA Clipper

Streamers' best GTA 6 moments in, finished vertical clips out. Everything renders on this Mac. The only outside calls
are Twitch (to find and download clips) and the user's own logged-in Claude Code (to check each moment and find the
webcam). No paid API.

## First run: setup

Once per machine, before anything else:

```bash
bash .claude/skills/gta-clipper/setup.sh
```

It installs ffmpeg, whisper-cpp and Deno through Homebrew if missing, builds a Python venv inside this skill folder
(with a current yt-dlp), downloads the small Whisper model (466 MB) and checks Claude Code is installed. macOS only.

## Twitch keys (free, about five minutes)

`top` and `auto` find the most viewed clips through Twitch's API, which needs a free app. Walk the user through it:

1. Log in at https://dev.twitch.tv/console with their Twitch account (sign up if needed, and open the email Twitch
   sends to verify the account).
2. **Two-factor authentication must be on**, or Twitch will not let them register an app: in Twitch's Security and
   Privacy settings, enable 2FA, then refresh the console.
3. In the console: **Applications**, then **Register Your Application**.
   - Name: anything, but it must be unique across Twitch, e.g. `gta-clipper-<their name>`
   - OAuth Redirect URLs: `http://localhost`, then **Add** (this tool never uses it, the form just needs one)
   - Category: whichever fits; it does not change the keys
   - Tick *I'm not a robot*, then **Create**.
4. Back on Applications, click **Manage** on the new app. Copy the **Client ID**. Click **New Secret** and copy the
   secret straight away.
5. Put both in a file called `.env` in the folder they run from (copy `.env.example`):

   ```
   TWITCH_CLIENT_ID=paste-the-client-id
   TWITCH_CLIENT_SECRET=paste-the-secret
   ```

6. Test with `clip.py top`. A list of clips means the keys work. *Twitch turned the keys down* means one was pasted
   wrong: click New Secret and paste both again.

Never print the secret, never commit `.env` (the `.gitignore` keeps it out), never put it in a prompt.

## Make clips

Always run with the skill's own Python, from the user's project folder:

```bash
PY=.claude/skills/gta-clipper/.venv/bin/python
C=.claude/skills/gta-clipper/scripts/clip.py

$PY $C top                     # the 10 most viewed GTA 6 clips of the last 24 hours (needs keys)
$PY $C auto --n 3              # make 3 clips from the most viewed, one per streamer (needs keys)
$PY $C make "<clip link>"      # make a clip from a link the user picked (no keys needed)
```

Options:
- `--color yellow` (default), `pink`, `cyan`, `green`, `red`, `white`, or a hex code like `#ff8800`: the word highlight,
  the seam and the streamer's name plate.
- `--hours 48`: look further back on Twitch. `--n`: how many to list or make.
- `--game "Grand Theft Auto V"`: another game, by its exact name on Twitch. The moment check follows it.
- `make` takes several links at once. **Quote every link** (zsh breaks on the `?`). Any link yt-dlp reads works
  (Twitch, YouTube, Kick); with keys, a Twitch clip link also gets the stream around it for the build-up.

### What happens to each clip

1. **Download:** with keys, the viewers' clip plus 30 seconds of the stream before and 20 after (the build-up and the
   reaction). Without keys, the clip itself.
2. **Words:** local Whisper writes down every word the streamer says, with its time.
3. **Check:** Claude looks at eight frames and the words and decides: is it the right game, real gameplay (not a
   cutscene, no chat over the game, nothing adult), does it pay off, and where it should start and end. A clip that
   fails is skipped with the reason.
4. **Webcam:** Claude finds the streamer's webcam on two frames. No webcam, no clip (the look needs them on top).
5. **Render:** 1080x1920, webcam on top, game below, the loudest moment first as the hook, the words three at a time
   with the spoken one lit, a label over the seam, the streamer's name on it, loudness set for the feed.

`auto` skips clips it has already tried (`gta-clips/_twitch/used.json`), takes one clip per streamer, ignores clips
under 15 seconds or under 100 views, and deletes each download once its clip is made.

**Run it in the background** and relay its progress: it prints each clip's steps (*Downloading*, *Reading what X
says*, *Claude is checking the moment*, *Claude is finding the webcam*, *Rendering*) and a *Finished* line with the time.
A skipped clip says why in one line; pass that on word for word. Any other problem ends with one `Stopped:` line.

### Where clips land

`gta-clips/clips/<streamer>-<kind>-....mp4`, each with a `.json` beside it holding the YouTube `title`, a
`post_caption` crediting the streamer, the moment in one sentence, and the checks.

## Watch every clip before it is called done

The checks cannot see a bad crop or a wrong word. For every finished clip:

1. Pull frames: `ffmpeg -v error -i <clip>.mp4 -vf fps=0.5,scale=360:-1 <tmp>/f-%02d.jpg`
2. Open every frame and check: the webcam shows the streamer's face (not cut off), the game is readable, the words are
   right and on screen, nothing cut off at the edges.
3. Show the user the clip path, its title and post caption from the `.json`, and what the frames showed. Say what you
   did not check (you cannot hear it).

## Rules that keep a clip page alive

- **Credit the streamer.** Their name is on screen the whole clip; keep it in the post caption too.
- **If a streamer asks, take it down at once.** Skip anyone who says no clips.
- **Spread it out:** not the same streamer every post.
- **No story spoilers, nothing adult, no GTA or Rockstar in the page's name or logo.** The moment check already skips
  cutscenes and adult content.
- **Posting is the user's call.** This skill makes and checks clips; it never posts them.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `no Twitch keys yet` | do the Twitch keys section, then `clip.py top` to test |
| `Twitch turned the keys down` | New Secret in the console, paste both into `.env` again |
| `No ... clips on Twitch in the last 24 hours` | `--hours 48`, or check the game's exact name on Twitch |
| `skipped: no webcam` | that streamer plays without a camera; `auto` moves on to the next |
| `skipped: a story cutscene` or `not a moment worth a clip` | Claude's judgement; `auto` moves on |
| `could not download` | run `setup.sh` again (it updates yt-dlp); a deleted clip cannot be fetched |
| `Claude returned an error` | run `claude` once in a terminal to check you are logged in and under your usage limit |
| A font error | the fonts are macOS system fonts; this pack does not run on Windows or Linux |
