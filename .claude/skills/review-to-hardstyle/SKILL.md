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

**Why the rule is this strict.** Verbatim theatre — plays built from real
people's recorded speech — is the closest established practice to what this
skill does, and it borrows its ethics from oral history: interviewees consent,
they know how their words will be used, and they can withdraw them. A reviewer
has done none of that. They wrote a complaint to a shop, not a lyric, and they
cannot take it back once it is a chorus. The standing description of the
verbatim practitioner is "mouthpiece and censor all at once", which is exactly
the position here: nothing forces the choice of what to amplify except the
person making it. That is the whole reason for the no-usernames rule, the
staff-name rule, and for treating "who is this for" in `config/business.md` as
load-bearing rather than decorative.

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

**The form has a name.** What this step does is *erasure*: a found-poetry
technique where the poem is made by removing from a source text rather than
composing over it, usually a source nobody thought of as poetic. That is the
frame to write in. The lyric is already inside the review; the work is deciding
what to take out.

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

Two tests for any addition, and it has to pass both. First, the erasure test:
could this line have been produced by deleting from the review rather than
writing over it? Second, the standing-behind test: would the reviewer still
recognise their own complaint and still stand behind what the track now says on
their behalf? If either fails, cut the addition — a slightly rougher line is a
cheap price.

Keep lines short. Hardstyle vocals are chanted, not sung. **Count syllables, not
words** — four to eight per chanted line. Word count is the wrong unit: "always
clean and organized" is four words and seven syllables, "an hour just for milk"
is five words and five syllables, and it is the syllables that have to fit.
Long lines will not fit the rhythm and Suno will mangle them.

### Prosody — the part that decides whether a line lands

A chanted line is a rhythm before it is a sentence. Three things settle it:

**Start the payoff on a stressed syllable.** A stressed syllable in a weak
musical position is a "greedy" spot: it sounds hurried, and it costs the
listener the illusion of a real person making a real statement. That illusion is
the entire product here — a flat sentence from an actual customer — so it is
worth more than a tidy rhyme. "ROLL-back" is a trochee and lands on the
downbeat. "com-PLETE shopping place" opens unstressed and hits softer. Trimming
a leading unstressed word is usually free: "Just for milk" beats "It was just
for milk".

**Choose the line ending on purpose.** An open vowel at the end sustains and a
crowd can hold it — "on the FLOOR", "at this PLACE". A hard consonant cannot be
held and can only stab — "just for MILK", "roll-BACK". Both are useful; a drop
built on a stab wants more repetitions and shorter gaps than one built on a
sustain. Notice which one the payoff line gives you before building the drop
around it.

**Match resolution to the review.** Even numbers of lines feel resolved, odd
numbers push forward; symmetrical line lengths settle, asymmetrical ones
unsettle. So a complaint that never resolves — no apology, no fix — should not
be handed a tidy four-line drop. Give it three lines, or a fourth that is
shorter than the rest. A five-star review can have the even, symmetrical version;
it earned it.

**Write the call down.** Put a **Prosody** line in the session file for each
track: the payoff line, its syllable count, whether it opens stressed, whether
it ends open or closed, and what the drop does about it. This is judgement, not
measurement — there is no pronouncing dictionary in this project and adding one
would fail on exactly the brand names and misspellings worth chanting. Writing
the call down costs nothing and makes it checkable: the user can say the line
out loud and disagree in five seconds, which beats finding out in Suno. Say so
when a line breaks a guide and is kept anyway, and why.

Two cheap checks before committing to a payoff line:

- **Say it eight times out loud.** If you feel ridiculous and the line still
  holds, it is a hook. If it stops meaning anything by the fourth pass, it is a
  sentence, not a chant.
- **Leave a hole in front of it.** Cutting everything for half a second before
  the hook is standard practice in dance music, and it costs one direction:
  `[Build: silence, then one voice]`.

Repeat and truncate. This is the core chopping technique: state a phrase, repeat
it, then break it down into a fragment.

```
Wrong with the order.
Wrong with the order.
Nobody apologised.
Nobody... nobody...
```

Chopping is the principle; that triplet is only its most obvious form, and
reaching for it in every section of every track is what makes five tracks sound
like one track five times. These chop just as hard:

**Truncation ladder** — shed a word per pass, so the phrase decays in place.

```
An hour just for milk.
An hour just for milk.
An hour just for.
An hour.
```

**Isolation** — one word, alone, given a whole bar.

```
Locker.
Locker.
No one arrived.
```

**Call and answer** — split lifted phrases across two deliveries.

```
I went for baby milk.
(No one arrived.)
Which is in locker.
(No one arrived.)
```

Parentheses are the one thing Suno *sings* rather than obeys — it reads them as
a backing vocal set behind the lead, which is exactly what an answer line wants.
This is the only place they belong. Directions go in square brackets; see below.

**Front-loaded stutter** — hammer the first syllable, then release the phrase.

```
Ren-ren-renovation is horrible.
Nothing in stock anywhere.
```

Hyphens between syllables are the convention Suno reads as a stutter — an em
dash or a space is not the same instruction.

**Straight repetition** — no fragment at all. Some lines are already the right
length and lose their weight the moment they are broken.

```
Why are they on the floor.
Why are they on the floor.
Why are they on the floor.
```

Choose per track from the shape of the sentence, not by habit. A short flat line
wants isolation or straight repetition; a long clause wants the ladder; a line
with a natural pause in it wants call and answer.

Find the payoff line. Every usable review has one phrase that carries the whole
thing. That line goes in the DROP, chanted, usually three or four times. Pick it
before you write anything else and build backwards.

**Structure — use these tags:**

Suno reads the tags; which ones you use and in what order is your decision. The
seven-section shape below is the default anthem, not the only one. A set where
every track runs Intro → Verse → Build → Drop → Breakdown → Drop →
Outro sounds like one arrangement wearing five different sets of words, however
different the five reviews were — and that sameness is more audible than any
individual track's flaws.

**A — Full anthem.** The default. Best for a review with a turn in it: a
complaint that resolves, praise with a qualifier, anything with a "but".

```
[Intro: direction goes inside the bracket, after a colon]
Setup line from the review. Dry, spoken, scene-setting.

[Verse: chopped vocal stabs]
The key phrase, repeated and fragmented.

[Build: pitch shifting up, stutter effect]
Rising tension. Short fragments, escalating.

[Drop]
The payoff line. Chanted. Repeated 3x.

[Breakdown: melodic, filtered]
The emotional pivot — the qualifying clause, the "but", the resigned part.

[Drop: final, one new fragment]
Payoff line again, with one new fragment added.

[Outro]
One trailing fragment. Let it decay.
```

**Only canonical section names are reliable.** `[Intro]`, `[Verse]`,
`[Pre-Chorus]`, `[Chorus]`, `[Bridge]`, `[Break]`, `[Breakdown]`, `[Build]`,
`[Drop]`, `[Outro]`, `[End]`. Invented ones — `[Vocal Chop]`, `[Final Drop]` —
are not understood and get treated as noise or, worse, read out. Anything custom
goes after a colon on a canonical tag: `[Drop: final, one new fragment]` does
what `[Final Drop]` was meant to do, and actually works.

**B — Relentless.** Intro → Verse → Build → Drop → Drop (final) → Outro.
No breakdown, no melodic relief. For raw and uptempo material where a melodic
pivot would let the listener off the hook.

**C — Cold open.** Start on [Verse: chopped vocal stabs] with no spoken intro. The chant arrives
with no context and the setup line turns up later, in the breakdown. Good for a
one-line review with no scene to set.

**D — Breakdown first.** [Breakdown] → [Build] → [Drop] → [Verse] →
[Drop: final]. The melodic material opens and the chant answers it. Good for warm
reviews that would read as sarcastic if chanted from the top.

**E — Double hook.** Two payoff lines from the same review, one in [Drop] and
one in [Drop: final], each chanted in its own right. Only when the review
genuinely has two — forcing it produces a track with no centre.

Adapt further to the material — a two-line review doesn't need seven sections.
Drop sections rather than padding them with invented text.

**Production directions go inside the square bracket, after a colon** — never on
their own line in parentheses. Suno sings parentheses. A line reading
`(Dry monologue, low pitch filter)` is an instruction to the band delivered to
the singer, and it comes back as a backing vocal reciting the words "dry
monologue, low pitch filter". Square brackets are the channel for anything the
band is meant to do; parentheses are for words a voice is meant to say.

Directions are also where sameness creeps in: `[Build: pitch shifting up,
stutter effect]` on every track gives five identical builds. Draw from the range,
and let the review's tone pick.

- Delivery: `[Verse: dry monologue, low pitch filter]`,
  `[Verse: close mic, almost muttered]`, `[Verse: flat, spoken, no reverb]`,
  `[Drop: shouted, distorted]`, `[Intro: whispered, doubled]`,
  `[Verse: sung clean, one voice]`, `[Intro: deadpan, conversational]`
- Build: `[Build: pitch shifting up, stutter effect]`,
  `[Build: snare roll, rising filter]`, `[Build: silence, then one voice]`,
  `[Build: reverse cymbal, gated]`, `[Build: half-time, dragging]`,
  `[Build: kick drops out, vocal alone]`
- Breakdown: `[Breakdown: melodic, filtered pads]`, `[Breakdown: piano only]`,
  `[Breakdown: vocal dry, no music]`, `[Breakdown: wide reverb, distant]`,
  `[Breakdown: warm supersaw, sidechained]`

Two more formatting levers worth knowing: `*asterisks*` mark a sound effect
rather than a lyric, and ALL CAPS raises intensity on a line. Both are cheap;
neither is a substitute for a direction in the bracket.

## Step 4 — Write the Styles block

Comma-separated tags, densest first. Include, in roughly this order:

1. The variant and BPM from Step 2
2. Two or three hardstyle production signatures
3. Vocal treatment
4. Mood, derived from the review
5. Any business-context flavour

**Hardstyle production vocabulary**, grouped by what it controls. Take two or
three signatures per track, **from different families** — three lead words say
much less than a kick, a lead and a space.

- **Kick character:** distorted kick with pitched tail, kick rumble, short punchy
  kick, long distorted tail, overdriven gabber-style kick, half-time kick,
  double kick, reverse-bass kick pattern
- **Low end:** reverse bass, offbeat bass, sub rumble, rolling bassline
- **Lead and screech:** rawstyle screech, screech growl, euphoric supersaw,
  detuned saw stab, gated pluck, hoover lead, acid line, plucked bell lead,
  pitched siren
- **Breakdown texture:** melodic breakdown, sidechained pads, piano only,
  strings, warm supersaw, filtered pad swell, music-box lead
- **Vocal treatment:** pitched vocal chops, chopped vocal stabs, shouted chant,
  telephone-filtered vocal, doubled vocal, whispered layer, formant-shifted chop,
  crowd chant
- **Era and scene:** early rave stabs, 90s hardcore hoover, Y2K trance lead,
  underground raw, festival mainstage euphoric, warehouse
- **Space and mix:** dry and close, cavernous reverb, tape saturation, sidechain
  pumping, narrow and boxy, wide stereo lead

**Borrowing a neighbour's texture is a production choice; changing the genre tag
is not.** An overdriven gabber-style kick or a 90s hardcore hoover inside a raw
hardstyle track adds character and stays inside the tempo band the blend stage
needs. Writing "gabber" or "frenchcore" as the genre does not — it changes what
BPM Suno targets, and the set has to land near one master tempo. Vary the
texture freely; leave the genre and BPM to Step 2.

The 200-character ceiling applies to v4 and older. v4.5, v5 and v5.5 take about
1,000, and Suno's own guidance for those versions favours a fuller description of
how the arrangement progresses over a bare tag list. Dense tags still work and
stay the default here because they are easy to compare across five tracks; reach
for the longer form when a track needs its shape described rather than its
ingredients listed. Either way the field should not be padded — every descriptor
competes with the others for weight.

**Say where the vocal goes.** "vocal chops in the drop" places them; a bare
"pitched vocal chops" tag leaves Suno to guess, and it guesses the same way every
time.

**Negatives do not belong here.** "no melodic relief", "no breakdown" and the
like are unreliable in the style field — Suno reads the noun and not the "no".
Put them in the **Exclude Styles** field under Advanced Options, which is the
real control, and give the session file an **Exclude** block for that track so
the user knows to paste it.

**Vary the tags across the set.** `reverse bass` and `pitched vocal chops` fit
almost any hardstyle track, which is exactly why they end up in all five and
stop distinguishing anything. Two or three signatures per block, chosen because
this track needs them: a euphoric track earns `euphoric supersaw` and
`melodic breakdown`, a raw one earns `rawstyle screech` and `kick rumble`, and
neither needs the other's. If two Styles blocks in a session differ only by BPM
and one adjective, at least one of them is not describing its own track.

The variant and BPM lead, but the rest of the order is free — putting the mood
first, or the vocal treatment, changes what Suno weights.

## Step 5 — Check the set before writing it out

Sameness is invisible while writing one track at a time and obvious the moment
the five are read together. Lay the drafts side by side and check:

- **No two tracks share a section skeleton.** Five copies of shape A is the
  failure this step exists to catch. Vary it or say why the material forced it.
- **No parenthetical appears more than twice**, and no two build-ups are
  identical.
- **The chop techniques differ.** If every [Vocal Chop] is state / repeat /
  fragment, three of them are on autopilot.
- **No two drops have the same shape.** Payoff × 3 plus a tag is one option, not
  the format — try × 2 answered by a second line, a one-word stab, or the line
  split across two deliveries.
- **The Styles blocks differ by more than BPM**, and no two tracks draw their
  signatures from the same families — if every block is a kick word plus a
  lead word, the set has one sound described five times.
- **No line stands alone in parentheses as a direction.** Parentheses are
  sung. Every direction belongs inside its section's square bracket, after a
  colon; parentheses hold answer lines and ad-libs only.
- **Every section tag is a canonical one**, with anything custom after a
  colon. No `[Vocal Chop]`, no `[Final Drop]`.
- **Each payoff line starts on a stressed syllable**, and its ending —
  sustaining vowel or stabbing consonant — matches how its drop is built.
- **Resolution matches the review.** Unresolved complaints should not all
  have tidy even-numbered drops.
- **The BPMs are spread**, not clustered in a three-beat band. The blend stage
  timestretches onto one master tempo and corrections stay clean at 1–4%, so a
  set spanning 150 to 172 is a feature; five tracks at 155 waste the range.

Fixing this later means regenerating in Suno, so it is worth the minute now.
When something repeats for a real reason — two reviews that genuinely are the
same complaint — keep it and note it in the session file rather than inventing
difference the reviews do not support.

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
   the **Styles** block into the styles field, generate. Where a track has an
   **Exclude** block, paste it into Exclude Styles under Advanced Options.
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
**Shape:** <A-E, and one line on why this review wanted it>
**Prosody:** <the payoff line: syllable count, stressed or unstressed opener,
open or closed ending, and what the drop does about it>

### Lyrics
```text
<full lyrics block>
```

### Styles
```text
<styles block>
```

### Exclude
```text
<only when the track needs something kept out>
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
   "hook": "Don't bother.", "date": "2026-03-14", "variant": "raw",
   "review": "Third time this month something was wrong with the order..."}
]}
```

**`variant` is the Step 2 call, written down.** One of `euphoric`, `melodic`,
`raw-melodic`, `raw`, `uptempo` — exactly the value chosen from the tone table.
It costs nothing here and the visualiser uses it to decide how that track's hook
moves on screen, so a euphoric track glows and an uptempo one jumps. Leave it
out and the visualiser guesses from BPM, which works but re-derives a judgement
you already made while reading the review.

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
Shape B, relentless — the sign-off is the whole point and a melodic breakdown
would soften it. Note the drop is payoff x3 answered by a lifted line, and the
chop is state / repeat / fragment.

```
[Intro: dry monologue, low pitch filter]
Third time this month...
Something was wrong.

[Verse: chopped vocal stabs]
Wrong with the order.
Wrong with the order.
Nobody apologised.
Nobody... nobody...

[Build: pitch shifting up, stutter effect]
Rude when I asked.
Rude when I asked.
Third time. Third time.

[Drop]
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
Shape A, full anthem — this review has the turn that shape A exists for. Its
drop stacks four different lifted phrases rather than repeating one, which is a
third drop shape again.

```
[Intro: dry, filtered, close mic]
Waited twenty-five minutes.
Twenty-five minutes.

[Verse: chopped vocal stabs]
Clearly slammed.
Clearly slammed.
Three jobs at once.
Three jobs... three jobs...

[Build: snare roll, rising filter]
He apologised twice.
He apologised twice.
Twice. Twice. Twice.

[Drop]
Twenty-five minutes.
Three jobs at once.
Twenty-five minutes.
Clearly slammed.

[Breakdown: melodic, warm, filtered pads]
Genuinely excellent.
When it finally arrived.
Genuinely excellent...

[Drop: final, one new fragment]
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
