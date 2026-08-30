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

Load the file. Identify the review text column (it may not be labelled
obviously — look for the column with the longest free text). If there's a rating
column, keep it; it helps with tone but never overrides what the text says.

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
and repeat — you may not paraphrase into your own vocabulary. If a review says
"nobody apologised", the lyric is "Nobody apologised", not "no one said sorry".

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

Paste each pair into Suno's Advanced tab. Download WAVs to
`tracks/YYYY-MM-DD/` named `01-<slug>.wav`, `02-<slug>.wav`, ... in this order —
the numbering is how the visualiser matches tracks to hooks.

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
  {"title": "Third Time", "hook": "Don't bother.",
   "review": "Third time this month something was wrong with the order..."}
]}
```

`hook` is that track's DROP line. `review` is the source text, names already
stripped. Keep hooks under about five words — longer lines wrap and lose their
impact at the pulse.

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

**Flag it if every review is unusable.** A file of "Great!" and "5 stars" cannot
produce anything. Say so plainly rather than manufacturing lyrics from nothing.
