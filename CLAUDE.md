# 4PM on a Friday

Customer reviews in, beatmatched hardstyle set with a synced visualiser out.

Directory and repo are `4pm-on-a-friday`. The display name is "4PM on a Friday"
— use that in the README title, the video, and anywhere it's presented.

Two skills in `.claude/skills/`, one manual step between them.

```
input/reviews.csv
      |
      |  skill: review-to-hardstyle
      v
  Lyrics + Styles prompts  ->  [MANUAL: paste into Suno, download]
                                        |
                                        v
                              tracks/YYYY-MM-DD/*.wav
                                        |
                                        |  skill: hardstyle-blend
                                        v
                              output/mix.wav + video.mp4
```

## First run

`python scripts/check.py` (Windows) or `python3 scripts/check.py` (mac/Linux)
verifies librosa, soundfile, pillow, pandas, ffmpeg, and fonts, and prints
platform-specific fixes. Do not start debugging pipeline failures until it
passes — most early problems are a missing ffmpeg.

**Check the platform before writing any shell command.** This project runs on
Windows as often as Linux. On Windows: `python` not `python3`, no
`--break-system-packages`, no `&&` in Windows PowerShell 5.1, backslash paths,
`Expand-Archive` not `unzip`. Getting this wrong wastes a round trip every time.

## Business context

`config/business.md` holds what the business is, who the output is for, the
brand voice, recurring review themes, and what is off limits. **Read it before
generating any prompts.** It is what stops every set sounding the same and what
keeps the tone appropriate to the audience.

If it is still full of placeholder comments, say so and ask the user to fill it
in rather than generating against nothing.

## The two skills

**`review-to-hardstyle`** — reads a CSV/Excel of reviews, curates ~5 with
chantable detail, maps each review's tone to a hardstyle variant (euphoric
through raw to uptempo), and writes paste-ready Lyrics and Styles blocks. The
lyrics use the reviewer's verbatim words, chopped and repeated. Read its
SKILL.md before running it — the chopping technique and the name-stripping rule
are both load-bearing.

**`hardstyle-blend`** — four stages. `analyze.py` emits BPM, key, Camelot code,
and energy shape per track. **You decide the running order from that JSON** —
that stage is judgement, not a script, and it is the reason the output is a set
rather than a concatenation. `blend.py` timestretches onto a master tempo and
crossfades on the beat grid. `visualize.py` renders the MP4.

## Working rules

**Suno is manual and stays manual.** There is no official Suno API. Every
third-party "Suno API" is a reverse-engineered wrapper of the consumer web app.
The most popular one (gcui-art/suno-api) requires a 2Captcha subscription plus
Playwright anti-detection patches and a ghost cursor to defeat bot detection,
and needs the user's session cookie in an env var. Do not add it, do not add a
reseller built on it, and do not suggest either. If asked, explain the cookie
exposure and account-ban risk rather than just declining.

The manual step costs about two minutes a session. `docs/session-*.md` is what
makes it cheap — keep that file good.

If full automation genuinely becomes necessary, the answer is the Eleven Music
API: official, licensed training data, no cookie, no captcha. Open question is
whether it handles hardstyle as well as Suno. Test before switching.

**Every generation run writes two files.** `docs/session-YYYY-MM-DD.md` holds
the prompts in paste order with a checklist; `docs/text.json` holds hooks and
source reviews for the visualiser. Write both in the same run. Reconstructing
`text.json` later from downloaded filenames is tedious and lossy.

**Filename order is load-bearing.** WAVs go into `tracks/YYYY-MM-DD/` as
`01-<slug>.wav`, `02-<slug>.wav`, ... matching the session file. That numbering
is how the visualiser matches audio to hooks. It is not the playback order —
that gets decided in the blend stage.

**Timestretch in blend, never resample.** Resampling would shift every track's
key and undo the harmonic ordering. `blend.py` uses ffmpeg `atempo`, which holds
pitch. Corrections inside a hardstyle set land at 1-4%, well within clean range.

**Draft the video at 720, render final at 1080.** Render time is roughly
real-time, so a ten-minute set is a ten-minute render. Do not discover a
typo at 1080.

**Strip staff names from reviews.** Service reviews name people constantly. A
track chanting a named employee's failures is a different and much worse
artifact than one chanting a complaint. Replace with a role or cut the clause.

## What Claude cannot do here

Cannot hear audio. The numbers confirm a mix is level-consistent and
beat-aligned; they do not confirm the transitions land or that a track sounds
good. Say so rather than asserting it — that is the user's call after listening.

Cannot run Suno. The WAV handoff is the boundary.

## Folder conventions

- `config/business.md` — business context. Committed; no customer data in it.
- `input/` — review exports. Gitignored; may contain real customer text.
- `tracks/YYYY-MM-DD/` — Suno downloads for that session. Gitignored.
- `output/` — mixes, videos, tracklists. Gitignored.
- `docs/session-YYYY-MM-DD.md` — prompts and checklist for that session.
- `docs/text.json` — hooks and review text for the visualiser.

Nothing audio or customer-facing is committed. The repo holds skills and
scripts only.
