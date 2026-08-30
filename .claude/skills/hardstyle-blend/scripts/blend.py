#!/usr/bin/env python3
"""Beatmatch and blend an ordered list of tracks into one continuous mix.

Takes an explicit order (decided upstream) and a master tempo, stretches each
track onto that tempo, then crossfades on phrase boundaries.

Tempo correction uses ffmpeg's atempo, which preserves pitch. That is the right
choice here: corrections are small (a few percent within a hardstyle set) and
resampling instead would shift every track's key, wrecking the harmonic
transitions the ordering was chosen for.

Usage:
    python3 blend.py --order order.json --out mix.wav

order.json:
{
  "master_bpm": 155.0,
  "crossfade_beats": 32,
  "tracks": [
    {"path": "...", "bpm": 152.4, "first_beat_s": 0.31, "title": "..."},
    ...
  ]
}
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
MAX_STRETCH = 0.15  # refuse beyond this; the track does not belong in the set


def atempo_chain(ratio: float) -> str:
    """ffmpeg atempo accepts 0.5-2.0 per stage; chain for anything outside."""
    stages = []
    r = ratio
    while r > 2.0:
        stages.append(2.0)
        r /= 2.0
    while r < 0.5:
        stages.append(0.5)
        r /= 0.5
    stages.append(r)
    return ",".join(f"atempo={s:.6f}" for s in stages)


def stretch(src: Path, dst: Path, ratio: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-filter:a", atempo_chain(ratio),
         "-ar", str(SR), "-ac", "2", str(dst)],
        check=True, capture_output=True,
    )


def load_stereo(path: Path) -> np.ndarray:
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if sr != SR:
        raise ValueError(f"{path.name}: expected {SR} Hz, got {sr}")
    if y.shape[1] == 1:
        y = np.repeat(y, 2, axis=1)
    return y[:, :2]


def equal_power_fade(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Equal-power curves. Linear fades dip in the middle -- audible on a
    continuous mix, where the two kicks briefly sum to something weaker than
    either."""
    t = np.linspace(0, 1, n, dtype=np.float32)
    return np.cos(t * np.pi / 2), np.sin(t * np.pi / 2)


def blend(order: dict, out_path: Path) -> dict:
    master = float(order["master_bpm"])
    xf_beats = int(order.get("crossfade_beats", 32))
    xf_samples = int((60.0 / master) * xf_beats * SR)

    mix = np.zeros((0, 2), dtype=np.float32)
    tracklist = []
    tmp = Path(tempfile.mkdtemp())

    for i, t in enumerate(order["tracks"]):
        src = Path(t["path"])
        ratio = master / float(t["bpm"])
        if abs(ratio - 1.0) > MAX_STRETCH:
            print(f"  REFUSED {src.name}: needs {(ratio-1)*100:+.1f}% stretch",
                  file=sys.stderr)
            continue

        staged = tmp / f"{i:02d}.wav"
        stretch(src, staged, ratio)
        y = load_stereo(staged)

        # Trim the pre-first-beat lead-in so downbeats align on the grid.
        lead = int(float(t.get("first_beat_s", 0.0)) / ratio * SR)
        if 0 < lead < len(y):
            y = y[lead:]

        start_sample = len(mix)
        if len(mix) == 0:
            mix = y.copy()
        else:
            n = min(xf_samples, len(y), len(mix))
            out_c, in_c = equal_power_fade(n)
            start_sample = len(mix) - n
            tail = mix[-n:] * out_c[:, None]
            head = y[:n] * in_c[:, None]
            mix = np.concatenate([mix[:-n], tail + head, y[n:]], axis=0)

        tracklist.append({
            "position": len(tracklist) + 1,
            "title": t.get("title", src.stem),
            "file": src.name,
            "start_s": round(start_sample / SR, 2),
            "timestamp": f"{int(start_sample/SR)//60}:{int(start_sample/SR)%60:02d}",
            "original_bpm": round(float(t["bpm"]), 1),
            "stretch_pct": round((ratio - 1) * 100, 2),
        })

    peak = float(np.max(np.abs(mix))) if len(mix) else 1.0
    if peak > 0:
        mix = mix * (0.891 / peak)  # ~ -1 dBFS

    sf.write(str(out_path), mix, SR, subtype="PCM_24")

    return {
        "output": str(out_path),
        "master_bpm": master,
        "duration_s": round(len(mix) / SR, 1),
        "duration": f"{int(len(mix)/SR)//60}:{int(len(mix)/SR)%60:02d}",
        "crossfade_beats": xf_beats,
        "tracklist": tracklist,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--out", default="mix.wav")
    args = ap.parse_args()

    order = json.loads(Path(args.order).read_text(encoding="utf-8"))
    result = blend(order, Path(args.out))
    Path(args.out).with_suffix(".tracklist.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
