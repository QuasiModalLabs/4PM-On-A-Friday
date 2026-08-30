#!/usr/bin/env python3
r"""Move Suno downloads into the session folder under their numbered names.

Suno names a download after the track title -- "The Right Place and Aisle
(Remastered).wav" -- and the pipeline needs "01-right-place.wav". Doing that by
hand is where the mistakes happen: wrong folder, wrong number, and renames that
collide with each other when two tracks swap positions.

This matches each downloaded file to a track in docs/text.json by title and
moves it into place. Download wherever is convenient, then run this.

Usage:
    python scripts/ingest.py                      # from tracks/, using newest session
    python scripts/ingest.py --from ~/Downloads   # straight from the browser folder
    python scripts/ingest.py --dry-run            # show the plan, move nothing

Windows: python. mac/Linux: python3.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aiff", ".aif", ".ogg"}

# Suno appends these to a download; they are not part of the title.
NOISE = re.compile(
    r"\b(remaster(ed)?|extended|version|final|v\d+|take\s*\d+|\(\d+\))\b",
    re.I)


def normalise(s: str) -> str:
    """Title or filename -> comparable token string."""
    s = re.sub(r"\([^)]*\)", " ", s)      # drop parenthesised suffixes
    s = NOISE.sub(" ", s)
    s = re.sub(r"[^0-9a-z]+", " ", s.lower())
    return " ".join(s.split())


def score(file_tokens: set[str], title_tokens: set[str]) -> float:
    """How well a filename matches a title.

    Containment of the filename's words in the title, because Suno truncates
    ("Five Points" for "I Give Five Points") far more often than it adds words.
    Jaccard breaks ties so an exact match beats a mere subset.
    """
    if not file_tokens:
        return 0.0
    contain = len(file_tokens & title_tokens) / len(file_tokens)
    jaccard = len(file_tokens & title_tokens) / len(file_tokens | title_tokens)
    return contain + jaccard / 100


def load_tracks(session: Path) -> list[dict]:
    data = json.loads(session.read_text(encoding="utf-8"))
    tracks = data.get("tracks", [])
    for i, t in enumerate(tracks, 1):
        if not t.get("file"):
            # Older text.json without an explicit target name: derive one that
            # matches the 01-<slug>.wav convention.
            slug = "-".join(w for w in normalise(t.get("title", "")).split()
                            if w not in {"the", "a", "an", "and", "of", "i"})[:40]
            t["file"] = f"{i:02d}-{slug or 'track'}.wav"
    return tracks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="docs/text.json",
                    help="track list to match against (default docs/text.json)")
    ap.add_argument("--from", dest="src", default="tracks",
                    help="folder holding the downloads (default tracks/)")
    ap.add_argument("--dest", help="session folder (default tracks/<session date>)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    session = Path(args.session)
    if not session.exists():
        print(f"no {session} -- run review-to-hardstyle first", file=sys.stderr)
        return 1
    tracks = load_tracks(session)

    dest = Path(args.dest) if args.dest else None
    if dest is None:
        dated = sorted(Path("docs").glob("session-20*.md"))
        if not dated:
            print("no docs/session-YYYY-MM-DD.md; pass --dest", file=sys.stderr)
            return 1
        dest = Path("tracks") / dated[-1].stem.replace("session-", "")

    src = Path(args.src).expanduser()
    pool = [p for p in src.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXT] if src.is_dir() else []
    if not pool:
        print(f"no audio files in {src}/", file=sys.stderr)
        return 1

    # Score every file against every title, then take best matches first so a
    # confident pairing claims its file before a weaker one can.
    pairs = []
    for t in tracks:
        tt = set(normalise(t["title"]).split())
        for p in pool:
            pairs.append((score(set(normalise(p.stem).split()), tt), t, p))
    pairs.sort(key=lambda x: -x[0])

    claimed_t, claimed_p, plan = set(), set(), []
    for sc, t, p in pairs:
        if sc < 0.5 or id(t) in claimed_t or p in claimed_p:
            continue
        claimed_t.add(id(t))
        claimed_p.add(p)
        plan.append((sc, t, p))
    plan.sort(key=lambda x: x[1]["file"])

    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    moved = 0
    for sc, t, p in plan:
        target = dest / t["file"]
        if p.resolve() == target.resolve():
            print(f"  ok       {t['file']:28} already in place")
            continue
        if target.exists():
            print(f"  SKIP     {t['file']:28} already exists, not overwriting")
            continue
        flag = "" if sc >= 1.0 else f"  (fuzzy {sc:.2f})"
        verb = "would move" if args.dry_run else "moved"
        print(f"  {verb:<11}{t['file']:28} <- {p.name}{flag}")
        if not args.dry_run:
            shutil.move(str(p), str(target))
        moved += 1

    missing = [t["file"] for t in tracks if id(t) not in claimed_t]
    leftover = [p.name for p in pool if p not in claimed_p]
    if missing:
        print(f"\n  still needed ({len(missing)}): " + ", ".join(missing))
    if leftover:
        print(f"  unmatched files: " + ", ".join(leftover))

    print(f"\n{moved} moved, {len(tracks) - len(missing)}/{len(tracks)} tracks "
          f"present in {dest}/")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
