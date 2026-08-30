---
name: review-to-hardstyle
description: Turn a spreadsheet of customer reviews into ready-to-paste Suno prompts — chopped lyrics built from the reviewers' own words, plus a matching hardstyle Styles prompt. Use this whenever the user has customer reviews, feedback, survey responses, testimonials, or support tickets in a CSV or Excel file and wants to make songs, tracks, or music out of them, or mentions Suno alongside reviews. Also use when they ask for hardstyle, hard dance, rawstyle, or uptempo prompts from any text data, or want to turn feedback into audio for marketing or internal use. Trigger even if they don't say "Suno" or "hardstyle" explicitly — "make a song out of our Google reviews" is this skill.
---

# Review to Hardstyle

Turns customer reviews into paste-ready Suno prompts. Each output is two blocks:
a **Lyrics** block (the reviewer's own words, chopped into hardstyle vocal
structure) and a **Styles** block (genre and production direction derived from
the review's tone plus the user's business context).

The whole conceit is that the words stay real. A review rewritten into generic
lyrics is worthless — the humour and the impact both come from hearing an actual
customer's actual sentence chanted over a reverse bass. Preserve their phrasing.

## What you need before starting

1. **The file** — CSV or Excel with review text in a column.
2. **Business context** — check `config/business.md` first, and read it if it
   exists. It should cover what the business is, who the output is for, the
   brand voice, recurring review themes, vocabulary worth keeping, and what is
   off limits.

If that file is missing or still full of placeholder comments, ask once before
generating: what's the business, and is this for internal fun, marketing, or
something else? Then offer to write the answers into `config/business.md` so it
isn't needed again.

Context does real work. "Who this is for" sets how sharp the output can be —
internal can be brutal, anything public should punch at the situation rather
than the customer. "Off limits" matters more than it looks: without it a vivid
complaint about a live legal dispute reads as good material.

## Step 1 — Read and select

**Find the file yourself; do not make the user name it.** If they did not give a
path, glob `input/` for `*.csv` and `*.xlsx`, ignore anything matching
`*example*`, and take the most recently modified. Say which file you picked.

Only ask if that turns up nothing, or if two non-example files were modified
within a few minutes of each other and you cannot tell which is the new export.
"I dropped the reviews in" plus a filename that is not quite what you expected is
the common case, and searching beats a round trip.

If nothing is in `input/`, check the user's Downloads and Desktop for a recently
modified CSV or Excel file before asking — exports frequently never get moved.

Load the file. `.xlsx` needs `pandas` with `openpyxl`; `.csv` needs pandas alone.

**Never call bare `pd.read_csv(path)`.** Review exports routinely come out of
Excel, Word, or a Windows review dashboard as Windows-1252 rather than UTF-8. One
curly apostrophe or en dash is a single byte (0x92, 0x96) that UTF-8 rejects, and
the whole run stops on `UnicodeDecodeError` before you have seen a single review.

```python
import pandas as pd

def load_reviews(path):
    if str(path).lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path), "excel"      # needs openpyxl
    # utf-8-sig also strips the BOM that Excel's "CSV UTF-8" export adds.
    # latin-1 maps all 256 byte values, so it never raises -- it is the
    # guaranteed last resort, not a real guess at the encoding.
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc), enc
        except UnicodeDecodeError:
            continue

df, encoding = load_reviews(path)
```

Say which encoding was used when it was not UTF-8. It tells the user their export
pipeline is producing Windows-encoded files, and it explains any odd punctuation
they see later in `text.json` or on the video.

Write your own output as UTF-8 regardless of what came in. A cp1252 apostrophe
read correctly and written back out as UTF-8 is fixed; one passed through blind
becomes a black diamond on the visualiser.

Identify the review text column — it may not be labelled obviously, so look for
the column with the longest free text. A common shape is two columns: reviewer
username first, review text second. Headers are often missing or unhelpful; go
by content, not by column name.

If there's a rating column, keep it. It helps with tone but never overrides what
the text says.

### Timestamps

If a column holds dates or times, parse it (`pd.to_datetime`, `errors="coerce"`)
and keep it. It is worth more than it looks:

**Clusters are signal.** Several complaints inside one week usually means
something specific happened — a staffing gap, a broken machine, a bad delivery.
Reviews from a cluster share a theme and make a stronger, more coherent set than
five unrelated grievances. Say so when you spot one.

**Trajectory matters for repeat reviewers.** The same username complaining in
March and again in August is a lasting problem; twice in one week is one bad
week. Different stories, different tone.

**Recency.** Prefer recent reviews when quality is otherwise equal — they
describe the business as it is now.

**Chronological sets.** Record each track's review date in `text.json` as
`date`. The blend stage can then order the set as a timeline rather than purely
by energy, which gives the running order a narrative. Note this as available;
don't decide it here.

Note that a username plus a timestamp identifies someone far more precisely than
either alone. The rule below still holds.

### Reviewer usernames

If a column holds reviewer names or usernames, **use it internally only.** It is
good for naming tracks, deduplicating, and spotting a repeat reviewer whose
complaints form a running theme.

**Never put a reviewer's username in the lyrics, the Styles prompt, the track
title, or `text.json`.** These are real people who wrote feedback, not
performers who agreed to appear. A track chanting a named person's complaint
back at them is a different artifact from one chanting the complaint, and it
follows that person around when their name is searched.

If the user explicitly asks to credit reviewers, say what that means in practice
before doing it — the name ends up in a video that may be posted publicly — and
let them decide with that in front of them.

Then **curate**. Do not generate a song per row.

Good source reviews have:
- concrete, specific detail ("waited 25 minutes for a flat white")
- a vivid phrase someone would actually chant
- enough length to chop — roughly 15 words minimum

Skip reviews that are:
- generic ("Great service!", "Would recommend")
- five stars with no detail — nothing to work with
- near-duplicates of one already selected

Default to 5 unless the user says otherwise. Aim for tonal range across the
set — all-furious gets monotonous fast, and the contrast between a euphoric
track and a raw one is most of the entertainment.

State which reviews you picked and why, briefly, before the prompts.

## Step 2 — Map tone to hardstyle variant

Hardstyle has a built-in sentiment axis. Use it — this is what makes outputs feel
deliberate rather than randomly assigned.

| Review tone | Variant | BPM | Character |
|---|---|---|---|
| Glowing, delighted | Euphoric hardstyle | 150–152 | Major key, supersaw leads, big melodic breakdown, anthemic |
| Positive but qualified | Melodic hardstyle | 150–155 | Minor key with an uplifting resolve, pitched vocal, warm |
| Mixed, resigned, tired | Raw-melodic hybrid | 153–157 | Minor, gritty kick, screeches under a melodic top |
| Annoyed, critical | Raw hardstyle | 155–160 | Dark minor, distorted screech leads, no melodic relief |
| Furious, ranting | Uptempo / rawphoric | 160–180 | Extreme distortion, relentless kick, chaotic |

Judge from the text, not the star rating. A three-star review with a savage line
in it makes a better raw track than its rating suggests.

## Step 3 — Write the lyrics

**Rules that matter most:**

Use the reviewer's actual words. Lift phrases verbatim. You may cut, reorder,
and repeat — and you may introduce a small number of your own words where they
make a line rhyme, scan, or land better, provided the core meaning and intent of
the review survive unchanged.

What that permits: a connecting "and" or "so" joining two lifted fragments, a
short tag that closes a rhyme, a filler syllable that fixes a limping line. What
it does not permit is swapping the reviewer's vocabulary for your own. If a
review says "nobody apologised", the lyric is "Nobody apologised", not "no one
said sorry" — added words go around their phrases, never over them.

The load-bearing phrases stay untouched: the drop line, and whatever concrete
detail makes the review specific rather than generic. Those are the reason the
track works, and they are the first thing a rhyme is tempted to smooth away.

The test for any addition is whether the reviewer would still recognise their
own complaint and still stand behind what the track now says on their behalf.
If not, cut the addition — a slightly rougher line is a cheap price.

Keep lines short. Hardstyle vocals are chanted, not sung. Four to seven words per
line. Long lines will not fit the rhythm and Suno will mangle them.

Repeat and truncate. This is the core chopping technique: state a phrase, repeat
it, then break it down into a fragment.

```
Wrong with the order.
Wrong with the order.
Nobody apologised.
Nobody... nobody...
```

Find the payoff line. Every usable review has one phrase that carries the whole
thing. That line goes in the DROP, chanted, usually three or four times. Pick it
before you write anything else and build backwards.

**Structure — use these tags:**

```
[Intro]
(production direction in parentheses)
Setup line from the review. Dry, spoken, scene-setting.

[Vocal Chop]
The key phrase, repeated and fragmented.

[Build-Up]
(Pitch shifting up, stutter effect)
Rising tension. Short fragments, escalating.

[DROP]
The payoff line. Chanted. Repeated 3-4x.

[Breakdown]
(Melodic, filtered)
The emotional pivot — the qualifying clause, the "but", the resigned part.

[Final Drop]
Payoff line again, with one new fragment added.

[Outro]
One trailing fragment. Let it decay.
```

Adapt the structure to the material — a two-line review doesn't need seven
sections. Drop sections rather than padding them with invented text.

**Parenthetical production directions** go under section tags, not in the sung
lines. They steer Suno's delivery: `(Dry monologue, low pitch filter)`,
`(Pitch shifting up, stutter effect)`, `(Screaming, distorted)`.

## Step 4 — Write the Styles block

Comma-separated tags, densest first. Include, in roughly this order:

1. The variant and BPM from Step 2
2. Two or three hardstyle production signatures
3. Vocal treatment
4. Mood, derived from the review
5. Any business-context flavour

**Hardstyle production vocabulary** — draw on these, they're what the genre
actually sounds like:

reverse bass, distorted kick with pitched tail, screech lead, euphoric supersaw,
gated pluck, melodic breakdown, pitched vocal chops, hard dance anthem,
sidechained pads, detuned saw stab, rawstyle screech, kick rumble

Keep it under about 200 characters. Suno responds to dense tag lists, not prose,
and long style fields dilute.

## Output format

Write a session file, then summarise in chat. The file is the deliverable —
hunting for a prompt in a chat log later is the friction this removes.

**Write `docs/session-YYYY-MM-DD.md`** using today's date:

```
# Session YYYY-MM-DD

Source: input/<filename>
Business: <one line from config/business.md>

## What to do with this file

1. Open Suno and switch to **Custom / Advanced** mode (the plain prompt box
   ignores the section tags).
2. For each track below: copy the **Lyrics** block into the lyrics field, copy
   the **Styles** block into the styles field, generate.
3. Download each result. **Anywhere is fine** — your Downloads folder, the
   desktop, `tracks/`. Do not rename anything.
4. When they are all downloaded, run:

       python scripts/ingest.py --from <wherever you downloaded them>

   That matches each file to its track by title and moves it into
   `tracks/YYYY-MM-DD/` under the right number. Add `--dry-run` to preview.
   Re-run it as many times as you like; it skips what is already in place, so
   downloading a few at a time is fine.
5. Tell Claude the tracks are in.

- [ ] 01 — <title>
- [ ] 02 — <title>
- [ ] 03 — <title>

---

## 01 — <title>

**Source review:** <original text>
**Read:** <one line: tone, chosen variant, why>

### Lyrics
```text
<full lyrics block>
```

### Styles
```text
<styles block>
```

---

## 02 — <title>
...
```

Fenced blocks matter — they give a one-click copy button in most editors, and
keep the section tags from being rendered as markdown headings.

**Also write `docs/text.json`** in the same run, in track order, so the
visualiser has hooks and review text without reconstruction later:

```json
{"tracks": [
  {"title": "Third Time", "file": "01-third-time.wav",
   "hook": "Don't bother.", "date": "2026-03-14",
   "review": "Third time this month something was wrong with the order..."}
]}
```

`hook` is that track's DROP line. `date` is the review date if the source had
one — omit it otherwise. No username, ever. `review` is the source text, names already
stripped. Keep hooks under about five words — longer lines wrap and lose their
impact at the pulse.

**`file` is the target filename**, `NN-<slug>.wav` matching this track's number
in the session file. Always write it. It does two jobs: `scripts/ingest.py` uses
it to put each Suno download under the right name, and `visualize.py` prefers it
over positional matching when captioning, so a running order that differs from
the download order still captions correctly. Keep the slug short and recognisable
— two or three words from the title.

**Then in chat**, give only a short summary: which reviews were picked, the
variant chosen for each, anything skipped and why. Do not paste the full prompts
into chat as well — the file is where they live.

## Worked examples

**Example 1 — negative review, raw hardstyle**

Source: *"Third time this month something was wrong with the order. Nobody apologised. Rude when I asked about it. Don't bother."*

Read: cold, repeat-offence anger with a dismissive sign-off. Raw hardstyle, 158.

```
[Intro]
(Dry monologue, low pitch filter)
Third time this month...
Something was wrong.

[Vocal Chop]
Wrong with the order.
Wrong with the order.
Nobody apologised.
Nobody... nobody...

[Build-Up]
(Pitch shifting up, stutter effect)
Rude when I asked.
Rude when I asked.
Third time. Third time.

[DROP]
Don't bother.
Don't bother.
Don't bother.
Nobody apologised.

[Outro]
Don't... bother...
```

Styles: `raw hardstyle, 158 BPM, distorted kick with pitched tail, rawstyle screech lead, reverse bass, cold aggressive pitched vocal chops, dark minor, no melodic relief`

**Example 2 — mixed review, raw-melodic hybrid**

Source: *"Waited 25 minutes for a flat white. The staff were clearly slammed and one guy was doing three jobs at once. He apologised twice. Coffee was genuinely excellent when it finally arrived."*

Read: frustration with real warmth underneath and a positive resolution — the breakdown carries the turn. Raw-melodic, 155.

```
[Intro]
(Dry, filtered, close mic)
Waited twenty-five minutes.
Twenty-five minutes.

[Vocal Chop]
Clearly slammed.
Clearly slammed.
Three jobs at once.
Three jobs... three jobs...

[Build-Up]
(Pitch shifting up, stutter effect)
He apologised twice.
He apologised twice.
Twice. Twice. Twice.

[DROP]
Twenty-five minutes.
Three jobs at once.
Twenty-five minutes.
Clearly slammed.

[Breakdown]
(Melodic, warm, filtered pads)
Genuinely excellent.
When it finally arrived.
Genuinely excellent...

[Final Drop]
Twenty-five minutes.
Genuinely excellent.
Three jobs at once.

[Outro]
When it finally arrived...
```

Styles: `raw melodic hardstyle, 155 BPM, gritty kick, reverse bass, screech lead under warm supersaw breakdown, pitched vocal chops, weary but hopeful, minor with major resolve`

## Guardrails

**Strip personal names.** Service reviews frequently name staff. Replace with a
role ("one guy", "the barista") or cut the clause. A track chanting a named
employee's failures is a different and much worse artifact than one chanting a
complaint, and it will follow that person around. Do this silently — no need to
announce it, just don't reproduce the name.

**Drop slurs and abuse.** Some reviews are just nasty. Suno will reject them and
the output isn't worth having. Skip the review rather than sanitising it into
something toothless — say briefly that you skipped one.

**Don't invent grievances.** If the review is thin, the track is short. Padding
with plausible-sounding complaints the customer never made produces a song that
misrepresents real feedback, which matters if this is going anywhere public.

The rhyme and flow latitude in Step 3 does not loosen this. Added words may
smooth a line; they may never introduce a grievance, a fact, a number, or an
intensifier the review does not contain. Making someone sound angrier than they
wrote is the same error as inventing the complaint outright.

**Flag it if every review is unusable.** A file of "Great!" and "5 stars" cannot
produce anything. Say so plainly rather than manufacturing lyrics from nothing.
