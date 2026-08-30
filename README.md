# 4PM on a Friday

Turn a spreadsheet of customer reviews into a beatmatched hardstyle set with a
synced visualiser.

Everything the customers said, at the volume it felt like.

https://github.com/user-attachments/assets/8910be28-4121-4cc4-9961-63ffaad3ff82

*40 seconds from the closing track of a five-track set. The words on screen are
a real review, chopped and chanted.*

## Why this exists

In the modern firm, customer feedback gets rolled up and metricised into a KPI.
Great for reporting. Great for management. Less great for the actual feeling
behind the feedback, which collapses into a number somewhere on a dashboard.

CSAT moved 4.2 to 4.1. Nobody in the room feels anything. Someone suggests
digging into the drivers.

This puts a dimension back without losing what prompted the feedback in the
first place. The lyrics are the reviewers' own words — chopped, repeated,
chanted. Not summarised, not paraphrased, not sentiment-scored into a bucket.
The actual sentence, at volume, over a reverse bass. That is the whole conceit,
and it is why the pipeline refuses to rewrite anyone's words into something
tidier: a review turned into generic lyrics is worthless, because the humour and
the impact both come from hearing what someone actually typed.

Then, once a week, everyone hears it together. Not a corporate ritual — an
actual experience of what the product does to the person on the other end of it.

Ten minutes a week, collectively feeling the pain we need to fix and the joy we
already deliver.

That is the name. 4PM on a Friday is the slot.

## How it works

```
input/<any export>.csv
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

Two skills and one manual step. Claude curates the reviews, writes the Suno
prompts, decides the running order, blends, masters and renders. You paste the
prompts into Suno and listen to what comes back.

The set is mastered twice, because one master does not win everywhere:
`--profile device` for people at their desks on laptops and headphones, and
`--profile club` for the room with the actual speakers. Same mix, different
delivery; the difference is measured and reported rather than guessed at.


## Design rationale

### Why Suno, and why it stays manual

There is no official Suno API. Every third-party "Suno API" is a
reverse-engineered wrapper around the consumer web app. The most popular one
needs a 2Captcha subscription, Playwright anti-detection patches and a ghost
cursor to defeat bot detection, and wants your session cookie in an environment
variable.

That is not rejected because it is difficult. It is rejected because it means
handing your account credentials to a scraper that is one detection update away
from breaking, and one terms-of-service enforcement away from a ban. No
automation of a two-minute step is worth that.

So the Suno step is manual, and the pipeline is built around that boundary
rather than pretending it away. `docs/session-YYYY-MM-DD.md` is the handoff:
every prompt in paste order, fenced for one-click copy, with a checklist.
`scripts/ingest.py` is the return path: download anywhere, under whatever name
Suno gives the file, and it sorts them out.

### The manual step is a taste gate, not a tax

This is the part worth being honest about: **the manual step is not purely a
cost.**

Suno output varies between generations of the identical prompt. Sometimes a
track comes back exactly as intended; sometimes it comes back merely pleasant,
which for this project is a failure. One track in a recent set was styled
"absurdly triumphant" over a review praising fresh paint in a parking lot. The
entire joke is the mismatch between the subject and the treatment. A version
that sounds nice instead of oversized is worthless, and no amount of prompt
engineering tells you which one you got.

Someone has to listen and decide. That judgement is the only point in the
pipeline where taste applies, and taste is precisely the thing that does not
automate. The two minutes buys a human ear at the one place it matters. Full
automation would not remove that work — it would remove the check, and ship
whatever came back first.

Everything on either side of that boundary is automated hard, which is what
makes the boundary affordable.

### Eleven Music was tested, and lost on the thing that matters

The obvious objection to all of the above is that Eleven Music has an official
API — licensed training data, no cookie, no captcha, no scraper. On paper it
removes the entire problem.

So it was tested rather than assumed. The same prompts went through both
services and the output was scored by three Toronto ABGs — VELD regulars who
hear this genre constantly and are not audio engineers, which is exactly the
right panel for output whose only job is to land on a dancefloor.

The result was not close, and it split cleanly:

| | Suno | Eleven Music |
|---|---|---|
| Vocal chops | **won** | |
| Non-generic character | **won** | |
| Audio distinction | | **won** |

Eleven Music genuinely produces the cleaner, better-separated audio. It does not
matter here. The vocal chops *are* the product — this pipeline exists to hear a
real customer's real sentence chanted over a reverse bass, and a service that
renders that more cleanly but less convincingly has lost at the only thing being
asked of it. "Non-generic" is the same finding from the other direction: a track
that sounds like competent hardstyle and nothing else is a failure, because the
joke is entirely in the specificity.

So the trade is deliberate and it is the right way round: this project gives up
the API to keep the vocal chops, and pays for that with two manual minutes.

Caveat, honestly: n=3, one genre, not a blind protocol, one point in time. It is
enough to settle the decision for now and not enough to be a general claim about
either service. Worth re-running if Eleven Music ships a model update — the API
is still the better platform in every respect except the one that decides it.

### Ordering is judgement, not a script

`analyze.py` emits BPM, key, Camelot code and energy shape per track. It does
not choose the running order — a person or Claude does, reasoning from those
numbers plus knowledge of which track is euphoric and which is furious, and
then has to explain the choice.

That is deliberate. Alphabetical ordering wastes the effort of beatmatching, and
a set that opens at peak energy has nowhere to go. The middle stage is the
reason the output is a set rather than a concatenation.

Real trade-offs show up here. A recent set had one track whose key sat five
steps from everything else on the Camelot wheel; the running order that gave the
best energy arc put that clash next to a euphoric track, where nothing hides it.
Chronological order put it next to the most distorted track in the set, where
the clash is covered. Chronological won, at the cost of the peak landing early.
There is no formula that produces that answer.

### Timestretch, never resample

`blend.py` corrects tempo with ffmpeg `atempo`, which preserves pitch.
Resampling would be simpler and would shift every track's key, undoing the
harmonic ordering the previous stage just spent its judgement on.

Corrections inside a hardstyle set land at 1–4%, comfortably inside the range
where the stretch is inaudible. Pick the master tempo as the geometric mean of
the tempo clusters rather than the median — on a set split between 152 and 161.5
BPM, the median forces one group to −5.9% while the mean holds everything to
3.1%.

### Loudness is a delivery decision, not a quality one

The mastering stage started with the obvious target. Commercial hardstyle masters
sit around −6 to −8 LUFS, so it defaulted there. That was wrong, and the way it
was wrong is the interesting part.

Suno's output arrives around −14 LUFS with −4 dBTP — already dynamic, with
headroom, needing no rescue. Measured on a real set, every decibel above where
the blend already lands is paid for in transients: pushing one track to −11.5
needs no limiting at all, to −9.2 needs 19.9% of the file limited, to −8.9 needs
33.8%. The assembled mix is worse again, because crossfades sum two tracks and
raise density further. Short-term crest — which on hardstyle *is* the kick —
went from 9.20 dB at the blend to 8.25 at −9 and 7.83 at −8.

So the default is now −11.5 LUFS: exactly where the blend sits, limiter never
engaged, nothing given up. The master became a safety pass — level matching,
peak ceiling, mono check — rather than a loudness push.

Then listening on real speakers complicated it again. The louder, limited
version genuinely sounded better on a system with subs, and worse on laptops.
Both were true at once, which is why there are two profiles instead of one
compromise. On a rig that can move air, limiting reads as density and power; on
a small driver there is no sub to carry it and the same limiting only costs
clarity.

Two things worth stealing from this. **Level-match before you A/B anything** —
louder always flatters, so an unmatched comparison tells you nothing, and the
first comparison here was unmatched and nearly led to the wrong call. And when
the numbers and the ears disagree, the ears are describing a playback system the
numbers never modelled.

## Setup

Activate a virtual environment first. `check.py` fails hard if a `.venv` exists
here and is not active, because otherwise packages install into one interpreter
while the pipeline runs on another, and every symptom afterwards is misleading.

### Windows

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```

**Close and reopen your terminal** so PATH picks them up. Then:

```
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
python scripts\check.py
```

Use `python`, not `python3`. Windows PowerShell 5.1 has no `&&` — put commands
on separate lines or use `;`. In `cmd`, `&&` is fine.

### macOS

```bash
brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/check.py
```

### Linux

```bash
sudo apt install ffmpeg fonts-dejavu
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/check.py
```

`check.py` verifies the venv, librosa, soundfile, numpy, pillow, pandas,
openpyxl, ffmpeg, the ffmpeg filters the mastering pass needs (`ebur128`,
`alimiter`, `bass`, `treble`) and fonts, and prints platform-specific fixes for
anything missing. Do not start debugging pipeline failures until it passes — most early
problems are a missing ffmpeg.

## Use

**0. Fill in `config/business.md`.** Once, before anything else. What the
business is, who the output is for, the brand voice, recurring themes, what is
off limits. The skill reads it every run, and it is what stops every set
sounding the same.

**1. Generate prompts.** Drop your review export in `input/` under any name —
CSV or Excel, any column layout. Then ask Claude Code:

> Make Suno prompts from the new reviews.

It finds the newest export itself, curates around five reviews with chantable
detail, maps each one's tone to a hardstyle variant, and writes
`docs/session-YYYY-MM-DD.md` plus `docs/text.json` for the visualiser.

**2. Generate in Suno.** Open the session file. For each track, copy the Lyrics
block into Suno's lyrics field and the Styles block into the styles field, in
Custom mode. Generate, listen, regenerate anything that came back flat.

Download wherever is convenient. **Do not rename anything.**

**3. Ingest.**

```
python scripts/ingest.py --from ~/Downloads
```

Matches each download to its track by title and files it under the right number.
Re-running is a no-op, so downloading in batches is fine. `--dry-run` previews.

**4. Blend, master and visualise.**

> Blend today's tracks and render a video.

Claude analyses tempo, key and energy, proposes a running order and explains
why, beatmatches, level-matches, crossfades, masters and renders the MP4.

**5. Play it at 4PM.** For the room, use the club master; for anyone joining on
headphones, the device one.

```
python .claude/skills/hardstyle-blend/scripts/master.py     --in output/mix.wav --out output/mastered-club.wav --profile club
```

`--list-profiles` prints both with the measured cost of each.

## Tests

```
python -m unittest discover -s tests
```

136 tests, about 45 seconds, no dependencies beyond what the pipeline already
needs. The audio ones are anchored on arithmetic rather than ears — a dual-mono
1 kHz sine at amplitude A measures exactly 20·log10(A) LUFS — and they pin the
ffmpeg behaviours that quietly corrupt a master if nobody is watching: the
limiter's auto-level default, its 5 ms lookahead, the 1/√2 mono-to-stereo
upmix, and the 192 kHz resample hiding inside `loudnorm`.

## What it cannot do

**Claude cannot hear the audio.** The numbers confirm a mix is beat-aligned,
that no track needed an audible stretch, and — since the mastering pass — the
measured loudness in and out, the true peak, the gain applied to each track, how
hard the limiter worked and how well the mix survives a mono sum. They do not
confirm that the transitions land, that a track is any good, or that the limiter
is not pumping. Anyone telling you otherwise from a JSON file is guessing. That
call is yours, after listening.

**Claude cannot run Suno.** The WAV handoff is the boundary, by design. See
above.

**Nothing can fix a weak generation.** There is no post-processing step that
turns a flat take into a good one. Regenerate it before ingesting, because
swapping a track later means redoing the ordering.

**Contract-free automation is not available.** Not "not yet built" — not
available, from a service with no public API and no supported client.

## Limitations and honesty

**Render time is roughly real-time at 1080p.** An 11-minute set is an 11-minute
render. Pre-flight at `--fps 1` first: same length, same code path, about 30
seconds, and it catches the faults that actually occur. Both bugs that reached a
finished render during development were resolution-independent, so drafting at
720 reproduced them exactly and revealed nothing.

**Ten paste operations for a five-track set.** Two blocks each. This is the
manual step and it is not going away; see the rationale above.

**Suno ignores requested BPM.** In one recent set, prompts asking for 157 and
163 both came back at 161.5. The blend stage corrects tempo anyway, so this
costs accuracy in the Styles prompt rather than in the output — but do not trust
the number you asked for.

**Suno names downloads after the track title**, and truncates them
unpredictably. `ingest.py` matches on title containment rather than equality for
exactly this reason.

**Review exports are frequently Windows-1252, not UTF-8.** A single curly
apostrophe out of Excel will stop a naive `pd.read_csv`. The skill falls back
through `utf-8-sig`, `cp1252`, `latin-1` and reports which one it used.

**The master is measured, not judged.** `blend.py` level-matches each track to
the median loudness of the set (clamped to 3 dB) and `master.py` takes the
finished mix to a loudness target under a true-peak ceiling, reporting every
number it used. What no number tells you is whether the limiter is pumping —
check `limited_pct` and `gr_max_db`, then listen. The tonal EQ is opt-in for the
same reason: it matches a published genre tilt, which makes a mix more average,
not better.

**The default loudness target is deliberately not chart-loud.** `--lufs -11.5`
is where the blend already sits, so the limiter never engages and the master
costs no transients — it is a safety pass, not a loudness push. Suno sources
arrive around -14 LUFS with real headroom; they do not need rescuing. Measured
on this set, every dB above the blend's own level is paid for in punch: short-
term crest runs 9.20 dB at the blend, 8.25 at -9 LUFS, 7.83 at -8, and on
hardstyle crest is the kick. `--lufs -9` and `-6` are there for a louder set,
with real limiting at both — use them with ears on the result. `master.py` stops
chasing a target past `--max-limiting-pct` and says how far short it stopped.

**A -1.0 dBTP master still overshoots through AAC.** Measured on the shipped
encode: 11 samples out of 29.9 million exceed full scale, peaking at +5.2 dBFS.
It is 0.000037% of the file and it predates the mastering pass — the earlier
video measured +2.5 dBTP from a quieter mix. Lower `--tp` if it ever matters.

**This does not replace the dashboard.** It is not a measurement instrument and
it does not aggregate anything. Five reviews a week, chosen for being chantable,
are not a representative sample and should never be presented as one. The KPI
still tells you what is happening across everyone; this tells you what one
Tuesday afternoon felt like for one person. The argument is that a team needs
both, not that the second replaces the first.

**Session state is markdown and JSON.** Fine at five tracks a week. It would
strain long before it became a library.

## Roadmap

- Re-run the Suno / Eleven Music comparison when Eleven ships a model update.
  It lost on vocal chops, not on platform, and that is the kind of gap a new
  model closes. Keep the reference set so the re-test is cheap.
- Make chronological versus energy-arc ordering an explicit switch instead of a
  per-session argument.
- Surface the pre-flight as a flag on the render itself, so it cannot be skipped.

## What's here

```
config/business.md         business context — fill this in first
.claude/skills/
  review-to-hardstyle/     reviews -> Suno prompts
  hardstyle-blend/         tracks -> mix + video
    scripts/analyze.py     tempo, key, energy per track
    scripts/blend.py       timestretch + level match + crossfade
    scripts/master.py      loudness, true-peak ceiling, mono check
    scripts/loudness.py    ebur128 measurement + gain staging
    scripts/visualize.py   audio-reactive MP4 with review text
    references/tilt.json   published genre EQ curve, with provenance
scripts/check.py           environment verification
scripts/ingest.py          Suno downloads -> numbered session files
tests/                     136 tests, stdlib unittest
docs/session-EXAMPLE.md    session file format
docs/text.json.example     visualiser text format
```

**Nothing audio or customer-facing is committed.** `input/`, `tracks/`,
`output/` and the real session files are gitignored — review exports and session
files quote customers verbatim. The repo holds skills, scripts and config only,
and a clone of it contains no customer data at all.

**The demo clip at the top is a deliberate exception, and it is not in the
repo.** It is hosted on GitHub's attachment CDN and embedded here, and it does
show a real review captioned on screen. That was a decision, not an oversight —
a tool like this is hard to judge from a description, and the whole point is
that the words are real. Everything the pipeline actually produces still stays
on the machine that made it.

See `CLAUDE.md` for the working rules.

## License

MIT.
