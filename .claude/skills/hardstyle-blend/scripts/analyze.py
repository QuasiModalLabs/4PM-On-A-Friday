#!/usr/bin/env python3
"""Analyse a folder of tracks and emit JSON for ordering decisions.

This script does NOT decide the order. It produces the numbers Claude reads to
decide -- tempo, key, energy shape, brightness, and how each track starts and
ends. Ordering is a judgement call that needs the review context too, so it
belongs upstream.

Usage:
    python3 analyze.py <folder> [--out analysis.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np

AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aiff", ".aif", ".ogg"}

# Krumhansl-Schmuckler profiles, used for a rough key estimate. Hardstyle is
# minor-dominant so the minor profile carries most of the weight in practice.
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Camelot wheel — adjacent numbers and same-number A/B swaps mix cleanly.
CAMELOT = {
    ("C", "maj"): "8B", ("C#", "maj"): "3B", ("D", "maj"): "10B", ("D#", "maj"): "5B",
    ("E", "maj"): "12B", ("F", "maj"): "7B", ("F#", "maj"): "2B", ("G", "maj"): "9B",
    ("G#", "maj"): "4B", ("A", "maj"): "11B", ("A#", "maj"): "6B", ("B", "maj"): "1B",
    ("C", "min"): "5A", ("C#", "min"): "12A", ("D", "min"): "7A", ("D#", "min"): "2A",
    ("E", "min"): "9A", ("F", "min"): "4A", ("F#", "min"): "11A", ("G", "min"): "6A",
    ("G#", "min"): "1A", ("A", "min"): "8A", ("A#", "min"): "3A", ("B", "min"): "10A",
}


def estimate_key(y: np.ndarray, sr: int) -> dict:
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best = (-1.0, "C", "maj")
    for i in range(12):
        rolled = np.roll(chroma, -i)
        for name, prof in (("maj", MAJOR), ("min", MINOR)):
            score = float(np.corrcoef(rolled, prof)[0, 1])
            if score > best[0]:
                best = (score, PITCHES[i], name)
    _, pitch, mode = best
    return {"key": f"{pitch} {mode}", "camelot": CAMELOT[(pitch, mode)]}


def analyse(path: Path) -> dict:
    y, sr = librosa.load(str(path), sr=44100, mono=True)
    dur = len(y) / sr

    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    tempo = float(np.atleast_1d(tempo)[0])

    # Hardstyle sits 150-180. Beat trackers often halve or double; pull into range.
    while tempo < 130:
        tempo *= 2
    while tempo > 200:
        tempo /= 2

    rms = librosa.feature.rms(y=y)[0]
    rms_db = 20 * np.log10(np.maximum(rms, 1e-9))
    # Energy in 10 buckets -- enough for Claude to see the shape without noise.
    buckets = [float(np.mean(b)) for b in np.array_split(rms_db, 10)]

    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))

    head = float(np.mean(rms_db[: max(1, len(rms_db) // 20)]))
    tail = float(np.mean(rms_db[-max(1, len(rms_db) // 20):]))

    return {
        "file": path.name,
        "path": str(path),
        "duration_s": round(dur, 2),
        "bpm": round(tempo, 2),
        "beat_count": int(len(beats)),
        "first_beat_s": round(float(beats[0]), 4) if len(beats) else 0.0,
        **estimate_key(y, sr),
        "energy_curve_db": [round(b, 1) for b in buckets],
        "peak_energy_db": round(float(np.max(buckets)), 1),
        "mean_energy_db": round(float(np.mean(buckets)), 1),
        "brightness_hz": round(centroid),
        "starts_quiet": bool(head < np.mean(buckets) - 6),
        "ends_quiet": bool(tail < np.mean(buckets) - 6),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="analysis.json")
    args = ap.parse_args()

    folder = Path(args.folder)
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT)
    if not files:
        print(f"No audio files in {folder}", file=sys.stderr)
        return 1

    tracks = []
    for p in files:
        print(f"  analysing {p.name}", file=sys.stderr)
        try:
            tracks.append(analyse(p))
        except Exception as e:
            print(f"  SKIPPED {p.name}: {e}", file=sys.stderr)

    bpms = [t["bpm"] for t in tracks]
    out = {
        "folder": str(folder),
        "track_count": len(tracks),
        "bpm_range": [round(min(bpms), 1), round(max(bpms), 1)],
        "suggested_master_bpm": round(float(np.median(bpms)), 1),
        "tracks": tracks,
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
