---
name: hardstyle-blend
description: Beatmatch and blend a folder of tracks into one continuous DJ mix, with the running order chosen deliberately rather than alphabetically. Use whenever the user has multiple audio files — Suno downloads, exported tracks, WAVs or MP3s in a folder — and wants them combined into a set, mix, megamix, blend, or single continuous file. Also use for "stitch these together", "make a set out of today's tracks", "blend the folder", or any request to sequence and crossfade several songs. Trigger even when they don't say "DJ mix" or "beatmatch" — "put all of these into one track" is this skill.
---

# Hardstyle Blend

Turns a folder of individual tracks into one continuous, beatmatched mix with a
tracklist. Built for hardstyle and hard dance, where tracks sit in a narrow BPM
band and tempo correction stays small, but works for anything similar.

Three stages: **analyse** (a script), **order** (your judgement), **blend** (a
script). The middle stage is the point. Alphabetical ordering wastes the effort
of beatmatching, and a set that opens at peak energy has nowhere to go.

## Stage 1 — Analyse

```bash
python3 scripts/analyze.py <folder> --out analysis.json
```

Needs `librosa`, `soundfile`, and `ffmpeg`. If librosa is missing:
`pip install librosa soundfile --break-system-packages`

Returns per track: `bpm`, `key`, `camelot`, `energy_curve_db` (10 buckets),
`peak_energy_db`, `brightness_hz`, `duration_s`, `first_beat_s`, and whether it
starts or ends quiet. Plus a `suggested_master_bpm` (the median).

Beat trackers halve and double tempo constantly. The script folds results into
130–200 BPM, but sanity-check anything that looks wrong — a track reported at
78 when everything else is 155 was probably detected at half time.

## Stage 2 — Decide the order

Read `analysis.json` and choose the sequence. You cannot hear these tracks, so
reason from the numbers and from whatever context you have about the tracks
themselves — if they came from `review-to-hardstyle`, you know which are
euphoric and which are raw, and that is better evidence than any audio feature.

**Build an energy arc.** Peak around 65–75% of the way through, not at the end.
Open below peak, climb, then leave one track after the peak to come down on.
`peak_energy_db` and `brightness_hz` together approximate intensity — raw
hardstyle reads bright and loud, euphoric reads bright but less dense, melodic
reads darker.

**Tempo should climb, gently.** Hard dance sets rise across their length. Order
roughly ascending by BPM, but let the energy arc win where they conflict —
`blend.py` corrects tempo anyway, so BPM order is a preference, not a constraint.

**Check adjacent keys.** Camelot codes one step apart (8A → 9A) or the same
number swapping letter (8A → 8B) mix cleanly. Two steps is passable. More than
that is a clash the listener will hear during the crossfade. When a good energy
order creates a bad key jump, put the harshest, most percussive transition
there — clashes hide under distortion.

**Use the start and end shape.** A track with `ends_quiet` true is a good
outgoing track. One with `starts_quiet` true is a good incoming one. Pairing
them gives you a natural transition for free.

**Chronological ordering is an option worth offering.** If `docs/text.json` has
a `date` per track, ordering the set as a timeline gives the running order a
narrative — the business's year, in sequence — which is more interesting than an
energy curve alone. It also usually produces a decent arc by accident, since
complaint clusters are naturally the intense stretch.

Where chronology and a good build conflict, say so and let the user choose.
Do not silently pick one. If you go chronological, note it in the tracklist so
the reason is visible.

**Refuse tracks that don't fit.** `blend.py` rejects anything needing more than
15% stretch. If a track is at 130 and the set is at 158, leave it out and say so
rather than dragging the master tempo to accommodate it.

Then write `order.json`:

```json
{
  "master_bpm": 156.6,
  "crossfade_beats": 32,
  "tracks": [
    {"path": "...", "bpm": 152.0, "first_beat_s": 0.31, "title": "Opener"}
  ]
}
```

Copy `path`, `bpm`, and `first_beat_s` straight from `analysis.json` — they must
match or the grid alignment fails. `crossfade_beats` of 32 is a long, smooth
blend; 16 is tighter and more energetic. Hardstyle usually wants 16.

**Explain the order before running the blend.** Two or three sentences on why
this sequence — the arc, the key moves, what goes where. This is the part the
user is actually asking you to do, and it should be visible.

## Stage 3 — Blend

```bash
python3 scripts/blend.py --order order.json --out mix.wav
```

Timestretches each track onto the master tempo with ffmpeg `atempo`, which
preserves pitch. That matters: resampling instead would shift every track's key
and undo the harmonic ordering. Trims each track's lead-in so downbeats land on
the grid, crossfades with equal-power curves, and normalises the result to
-1 dBFS.

Writes `mix.wav` and `mix.tracklist.json` with timestamps and per-track stretch
amounts.

## Stage 4 — Visualise (optional)

```bash
python3 scripts/visualize.py --audio mix.wav --tracklist mix.tracklist.json \
    --text text.json --out video.mp4 --size 1080 --fps 30
```

Renders a square MP4: the hook line centred and pulsing on the kick, log-spaced
spectrum bars, the source review underneath, track marker and progress bar.

Sync is exact by construction — every frame's brightness and bar heights are
computed from the audio at that timestamp, so there is nothing to drift and
nothing to key by hand.

`text.json` is what makes it worth watching. Without it you get titles only.

```json
{"tracks": [
  {"title": "Third Time", "hook": "Don't bother.",
   "review": "Third time this month something was wrong with the order..."}
]}
```

Write this from the `review-to-hardstyle` output: `hook` is that track's DROP
line, `review` is the source text. Keep hooks under about five words — longer
lines wrap and lose their impact at the pulse.

**Entries match audio by filename, not by position.** Entry *i* describes track
`0(i+1)-<slug>.wav`, so `text.json` stays in the `01-`/`02-` download order it
was written in and the running order chosen in Stage 2 can differ freely. Add an
explicit `"file": "03-slug.wav"` key to an entry to pin it. Do not reorder
`text.json` to match the mix — that breaks the convention and double-shuffles
the captions.

**Render time is the constraint.** Roughly real-time at 1080p: a ten-minute mix
takes about ten minutes. Square suits LinkedIn and Instagram; pass `--size 1080`
and crop later if you need vertical.

**Always do the 1-fps pre-flight before any full render.** Same resolution you
intend to ship, one frame per second:

```bash
python3 scripts/visualize.py --audio mix.wav --tracklist mix.tracklist.json \
    --text text.json --out preflight.mp4 --size 1080 --fps 1
```

A ten-minute mix takes about half a minute. Pull a frame from each track and
look at them:

```bash
ffmpeg -v error -ss 330 -i preflight.mp4 -frames:v 1 -y frame.png
```

This exists because two separate faults reached a finished 1080 render and
neither could have been caught by drafting at 720:

- Review text truncated mid-sentence. The line cap was resolution-independent,
  so the 720 draft was cut in exactly the same place and looked normal.
- A curly apostrophe rendered as mojibake, from a JSON read that used the
  platform default encoding. Also identical at every size.

Resolution is rarely what is wrong. Text, hook-to-track matching, and encoding
are, and all three are visible in a frame — so check frames cheaply and often,
and spend the full render once. Drafting at 720 is still worth it if you are
judging composition or font weight, but it is not the correctness gate.


Give the tracklist with timestamps, then the file. Keep it short — they want to
listen, not read. If a video was rendered, present that rather than the WAV.

```
1. 0:00  Opener        152 → 156.6 BPM  (+3.0%)
2. 2:41  Middle        157 → 156.6 BPM  (−0.2%)
3. 5:12  Peak          161 → 156.6 BPM  (−2.8%)
```

Flag anything worth knowing: a track that was refused, a stretch above about
8% (audible on sustained material), or a key clash you had to accept.

## Finding the day's folder

If the user refers to today's tracks without a path, look for a dated folder
(`2026-08-30`, `2026_08_30`, or similar) under the working directory or a
tracks/output directory. If several plausible folders exist, ask rather than
guessing — blending the wrong day wastes their time and yours.

## Notes

**Small stretches only.** Within a hardstyle set corrections are 1–4%, which
atempo handles cleanly. Beyond ~8% sustained tones start to warble. The script
refuses beyond 15%.

**You cannot hear the output.** The numbers confirm the mix is level and
beat-aligned; they do not confirm it sounds good. Say so rather than asserting
the transitions land — that is the user's call after listening.

**Mono-summing and loudness are not handled.** The output is peak-normalised
only. If they want a mastered set, that is a separate step.

**Dependencies.** `librosa`, `soundfile`, `pillow`, `ffmpeg`. Install with
`pip install librosa soundfile pillow --break-system-packages`. The visualiser
uses DejaVu fonts, present on most Linux systems; it falls back to a default
font if they are missing, which looks worse but still renders.
