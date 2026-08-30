# 4PM on a Friday

Turn a spreadsheet of customer reviews into a beatmatched hardstyle set with a
synced visualiser.

Everything the customers said, at the volume it felt like.

## Setup

### Windows (PowerShell)

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```

**Close and reopen PowerShell** so PATH picks them up.

```powershell
cd ~\Documents
Expand-Archive -Path ~\Downloads\4pm-on-a-friday.zip -DestinationPath .
cd 4pm-on-a-friday
pip install -r requirements.txt
python scripts\check.py
```

Use `python`, not `python3`. Windows PowerShell 5.1 has no `&&` — put commands
on separate lines or use `;`.

### macOS

```bash
brew install ffmpeg
pip3 install -r requirements.txt
python3 scripts/check.py
```

### Linux

```bash
sudo apt install ffmpeg fonts-dejavu
pip install -r requirements.txt --break-system-packages
python3 scripts/check.py
```

`check.py` verifies every dependency and gives platform-specific fixes for
anything missing. Do not start debugging pipeline failures until it passes.

## Use

**0. Fill in `config/business.md`.** Once, before anything else. What the
business is, who the output is for, brand voice, recurring themes, what is off
limits. The skill reads it every run.

**1. Generate prompts.** Put your review export in `input/`, then ask Claude Code:

> Read input/reviews.csv and make Suno prompts.

Writes `docs/session-YYYY-MM-DD.md` — every prompt in paste order with a
checklist — and `docs/text.json` for the visualiser.

**2. Generate in Suno.** Open the session file. For each track, copy the Lyrics
block into Suno's Lyrics field and the Styles block into the Styles field,
generate, download. Save WAVs to `tracks/YYYY-MM-DD/` as `01-<slug>.wav`,
`02-<slug>.wav`, ... matching the session file order. Tick the checklist as you
go.

**3. Blend and visualise.**

> Blend today's tracks and render a video.

Claude analyses tempo, key and energy, chooses a running order and explains why,
beatmatches, crossfades, and renders the MP4.

## What's here

```
config/business.md         business context — fill this in first
.claude/skills/
  review-to-hardstyle/     reviews -> Suno prompts
  hardstyle-blend/         tracks -> mix + video
    scripts/analyze.py     tempo, key, energy per track
    scripts/blend.py       timestretch + beat-aligned crossfade
    scripts/visualize.py   audio-reactive MP4 with review text
scripts/check.py           environment verification
```

See `CLAUDE.md` for the working rules.
