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
                     output/mix.wav -> mastered.wav + video.mp4
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

## Tests

```
python -m unittest discover -s tests          (Windows)
python3 -m unittest discover -s tests         (mac/Linux)
```

136 tests, about 45 seconds, no new dependencies — stdlib `unittest`, for the
same reason `pyloudnorm` was rejected. Run it after touching anything under the
skill's `scripts/`.

The suite is anchored on arithmetic, not on ears: a dual-mono 1 kHz sine of
amplitude A measures exactly 20·log10(A) LUFS, and everything about gain,
limiting and metering is checked against that. It also pins the ffmpeg
behaviours that silently corrupt a master — `alimiter`'s auto-level default, its
5 ms lookahead, the 1/√2 mono→stereo upmix, and the 192 kHz `loudnorm` resample
— so a future "simplification" fails loudly instead of shipping.

`master.py --selftest` still exists and overlaps deliberately: it needs no test
runner and is the thing to reach for when checking a machine rather than the
code.

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

**`hardstyle-blend`** — five stages. `analyze.py` emits BPM, key, Camelot code,
and energy shape per track. **You decide the running order from that JSON** —
that stage is judgement, not a script, and it is the reason the output is a set
rather than a concatenation. `blend.py` timestretches onto a master tempo,
level-matches the tracks and crossfades on the beat grid. `master.py` takes the
mix to a loudness target under a true-peak ceiling. `visualize.py` renders the
MP4.

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
scored by three Toronto ABGs, and Suno won on vocal chops and
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

Nothing downstream resamples either. This is why the mastering pass uses
`ebur128` + `alimiter` rather than ffmpeg's `loudnorm`: `loudnorm` resamples to
192 kHz internally (verified — 44100 in, 192000 out). Do not "simplify"
`master.py` into a one-line `loudnorm` call; the comment at the top of
`loudness.py` exists to stop exactly that.

**Master by numbers; never claim tone.** Every mastering stage reports what it
measured and what it did: integrated LUFS in and out, loudness range, true peak,
per-track gain, limiter gain reduction and the percentage of the file it
touched, stereo and bass correlation, mono-sum loss. State those as facts. Do
not say the master sounds better, warmer, punchier or fuller — you cannot hear
it.

**Default target is -11.5 LUFS at -1.0 dBTP, and that is on purpose.** It is
where the blend already sits, so the limiter never engages and the stage costs
no transients. Do not "fix" it upward to the commercial hardstyle figure: Suno
sources arrive around -14 LUFS with headroom, and measurement on a real set
showed every dB above the blend's level is paid for in punch — short-term crest
9.20 dB at the blend, 8.25 at -9, 7.83 at -8. The user listened and chose
-11.5. Louder is opt-in via `--lufs`, and the tool refuses to grind past
`--max-limiting-pct` chasing a number.

**Compare like for like.** If anyone reports the master sounding worse than the
raw tracks, level-match before judging — louder always flatters, so a louder
master that still sounds worse is real evidence, and an unmatched comparison is
none.

**Per-track level matching targets the set's median, not an absolute figure.**
The audible fault is relative, and the absolute level gets decided once, in
`master.py`. Corrections clamp at ±3 dB and clamping is reported by name.

**The tonal EQ is opt-in and stays that way.** `references/tilt.json` is a
published genre tilt that records its own provenance and its own limits. It
makes a mix more average, not better, and a genre curve is strictly worse than a
reference mix someone has actually listened to.

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

Cannot hear audio. The numbers confirm a mix is beat-aligned, level-matched, on
its loudness target and under its peak ceiling; they do not confirm the
transitions land, that a track sounds good, or that the limiter is not pumping.
Say so rather than asserting it — that is the user's call after listening.
`master.py --selftest` (in the skill's `scripts/`) is the substitute for ears on
the code itself: it checks the whole measurement and gain chain against
arithmetic ground truth, with no real audio.

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
