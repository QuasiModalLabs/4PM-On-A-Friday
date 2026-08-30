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
  Lyrics + Styles prompts  ->  [MANUAL: paste into Suno, download anywhere]
                                        |
                                        |  python scripts/ingest.py --from <folder>
                                        v
                              tracks/YYYY-MM-DD/NN-<slug>.wav
                                        |
                                        |  skill: hardstyle-blend
                                        v
                              output/mix.wav + video.mp4
```

## First run

Activate the venv first, then `python scripts/check.py` (Windows) or
`python3 scripts/check.py` (mac/Linux). It verifies librosa, soundfile, pillow,
pandas, openpyxl, ffmpeg, and fonts, and prints platform-specific fixes. Do not
start debugging pipeline failures until it passes — most early problems are a
missing ffmpeg.

It fails hard if a `.venv` exists here and is not active, because the packages
then install into a different interpreter from the one that runs the pipeline,
and every symptom afterwards is misleading.

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

**Eleven Music has already been evaluated. Do not propose it as an untested
idea.** Official API, licensed training data, no cookie, no captcha — better on
every platform axis. It lost anyway: the same prompts through both services,
scored by three Toronto hard-dance listeners, and Suno won on vocal chops and
non-generic character while Eleven won on audio distinction. Not close.

That result is decisive here because the vocal chops are the product. Cleaner
audio does not compensate for a less convincing chant of a real customer's
sentence.

Worth re-running only when Eleven ships a model update, and say that it is a
re-test of a settled question rather than an open one. n=3, one genre, not
blind — enough to decide, not a general claim.

**Every generation run writes two files.** `docs/session-YYYY-MM-DD.md` holds
the prompts in paste order with a checklist; `docs/text.json` holds hooks and
source reviews for the visualiser. Write both in the same run. Reconstructing
`text.json` later from downloaded filenames is tedious and lossy.

**Do not rename Suno downloads by hand.** `python scripts/ingest.py --from
<folder>` matches each download to a track in `docs/text.json` by title and moves
it into `tracks/YYYY-MM-DD/` as `01-<slug>.wav`, `02-<slug>.wav`, ... Download
anywhere; re-running is a no-op, so batches are fine. Renaming by hand is how
files end up in the wrong folder, and swapping two tracks' positions produces
renames that collide unless done in the right order.

**Filename order is load-bearing, and `text.json` carries it.** Each track's
`file` field is the target name, and it is what the visualiser matches audio to
hooks by — not list position. That means the download order and the playback
order are independent: playback gets decided in the blend stage and needs no
renaming. Always write `file`.

**Timestretch in blend, never resample.** Resampling would shift every track's
key and undo the harmonic ordering. `blend.py` uses ffmpeg `atempo`, which holds
pitch. Corrections inside a hardstyle set land at 1-4%, well within clean range.

**Pre-flight every render at `--fps 1`, then render final at 1080.** Render time
is roughly real-time, so a ten-minute set is a ten-minute render — but a
full-length pass at one frame per second takes about thirty seconds and
exercises the whole real code path. Pull a frame per track with
`ffmpeg -ss <sec> -i preflight.mp4 -frames:v 1 frame.png` and read the text.

The faults that reach a finished render are resolution-independent — a line cap
that truncated a review mid-sentence, a JSON read that rendered an apostrophe as
mojibake — so drafting at 720 reproduces them exactly and reveals nothing. Draft
at 720 to judge composition or font weight; the 1-fps pass is the correctness
gate.

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
  Gitignored; quotes reviews verbatim.
- `docs/text.json` — hooks, `file` targets, and review text for the visualiser.
  Gitignored; quotes reviews verbatim.
- `docs/session-EXAMPLE.md`, `docs/text.json.example` — synthetic. Committed as
  the format reference, and the gitignore negates them explicitly.

Nothing audio or customer-facing is committed. The repo holds skills and
scripts only.
