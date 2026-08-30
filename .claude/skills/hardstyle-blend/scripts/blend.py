#!/usr/bin/env python3
"""Beatmatch and blend an ordered list of tracks into one continuous mix.

Takes an explicit order (decided upstream) and a master tempo, stretches each
track onto that tempo, level-matches them, then crossfades on phrase boundaries.

Tempo correction uses ffmpeg's atempo, which preserves pitch. That is the right
choice here: corrections are small (a few percent within a hardstyle set) and
resampling instead would shift every track's key, wrecking the harmonic
transitions the ordering was chosen for.

Level matching targets the MEDIAN loudness of the set, not an absolute figure.
The audible problem between tracks is relative -- one track sitting under the
rest vanishes into its own crossfade -- and matching to the median moves the
least audio to fix it. The absolute level is decided exactly once, downstream in
master.py, so the two stages never fight.

Usage:
    python3 blend.py --order order.json --out mix.wav

order.json:
{
  "master_bpm": 155.0,
  "crossfade_beats": 32,
  "rationale": "why this sequence -- carried through to the tracklist",
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loudness as L  # noqa: E402

SR = 44100
MAX_STRETCH = 0.15  # refuse beyond this; the track does not belong in the set

# A track wanting more than this is mismatched with the set in a way gain cannot
# fix -- applying it silently would make that track's drop the loudest thing in
# the mix. Clamp, apply what we can, and say so.
GAIN_LIMIT_DB = 3.0

# Integrated loudness is dragged down by long quiet intros and breakdowns. When
# a track's short-term peak sits this far above its integrated figure, the gain
# match is being computed from an unrepresentative number.
QUIET_INTRO_WARN_LU = 8.0


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
    # -c:a pcm_f32le matters: without it ffmpeg defaults .wav to pcm_s16le, so
    # every track was being truncated to undithered 16-bit on the only signal
    # path into the mix -- and per-track gain would then amplify that
    # quantisation noise.
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-filter:a", atempo_chain(ratio),
         "-c:a", "pcm_f32le", "-ar", str(SR), "-ac", "2", str(dst)],
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


def blend(order: dict, out_path: Path, *, gain_match: str = "median",
          gain_limit: float = GAIN_LIMIT_DB, headroom_db: float = -1.0,
          keep_staged: bool = False) -> dict:
    master = float(order["master_bpm"])
    xf_beats = int(order.get("crossfade_beats", 32))
    xf_samples = int((60.0 / master) * xf_beats * SR)

    tmpdir = tempfile.TemporaryDirectory()
    tmp = Path(tmpdir.name)
    try:
        # --- pass 1: stage, stretch, trim, measure ----------------------------
        # Split into two passes because the median target cannot be known until
        # every SURVIVING track has been measured -- refused tracks must not skew it.
        staged = []
        for i, t in enumerate(order["tracks"]):
            src = Path(t["path"])
            ratio = master / float(t["bpm"])
            if abs(ratio - 1.0) > MAX_STRETCH:
                print(f"  REFUSED {src.name}: needs {(ratio-1)*100:+.1f}% stretch",
                      file=sys.stderr)
                continue

            staged_path = tmp / f"{i:02d}.wav"
            stretch(src, staged_path, ratio)
            y = load_stereo(staged_path)

            # Trim the pre-first-beat lead-in so downbeats align on the grid.
            lead = int(float(t.get("first_beat_s", 0.0)) / ratio * SR)
            if 0 < lead < len(y):
                y = y[lead:]

            # Measure AFTER the trim and stretch: that is the audio that actually
            # enters the mix. (This is also why the measurement does not live in
            # analyze.py, which sees the original file, mono and untrimmed.)
            m = L.measure(y)
            staged.append({"y": y, "t": t, "src": src, "ratio": ratio, "m": m})
            print(f"  {src.name}: {m['lufs_i']:+.1f} LUFS, TP {m['true_peak_dbfs']:+.1f} dBFS",
                  file=sys.stderr)

        if not staged:
            raise SystemExit("no tracks survived; nothing to blend")

        # --- gain targets ------------------------------------------------------
        lufs = [s["m"]["lufs_i"] for s in staged]
        finite = [x for x in lufs if x is not None and np.isfinite(x)]
        if gain_match == "off":
            target = None
        elif gain_match == "median":
            target = float(np.median(finite)) if finite else None
        else:
            target = float(gain_match)

        clamped = []
        gain_warnings = []
        if target is not None and finite:
            spread = max(finite) - min(finite)
            print(f"  gain match: target {target:+.1f} LUFS, spread {spread:.1f} LU",
                  file=sys.stderr)

        # --- pass 2: apply gain, then splice -----------------------------------
        mix = np.zeros((0, 2), dtype=np.float32)
        tracklist = []
        for s in staged:
            src, t, m = s["src"], s["t"], s["m"]
            gain_db = 0.0
            if target is not None and m["lufs_i"] is not None and np.isfinite(m["lufs_i"]):
                wanted = target - m["lufs_i"]
                gain_db = float(np.clip(wanted, -gain_limit, gain_limit))
                if abs(wanted) > gain_limit + 1e-9:
                    clamped.append(src.name)
                    msg = (f"{src.name}: wanted {wanted:+.1f} dB, clamped to "
                           f"{gain_db:+.1f} dB")
                    gain_warnings.append(msg)
                    print(f"  CLAMPED {msg}", file=sys.stderr)

            y = s["y"] if gain_db == 0.0 else L.apply_gain(s["y"], gain_db)

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
                "stretch_pct": round((s["ratio"] - 1) * 100, 2),
                "input_lufs": round(m["lufs_i"], 1) if m["lufs_i"] is not None else None,
                "input_true_peak_dbfs": m["true_peak_dbfs"],
                "gain_db": round(gain_db, 2),
            })

        peak = float(np.max(np.abs(mix))) if len(mix) else 1.0
        peak_before_db = L.lin_to_db(peak)
        norm_db = 0.0
        if peak > 0:
            norm_db = headroom_db - peak_before_db
            mix = mix * np.float32(L.db_to_lin(norm_db))

        sf.write(str(out_path), mix, SR, subtype="PCM_24")

        # Measure the assembled mix. Equal-power crossfades of two correlated kicks
        # can sum above either source, and this is where that becomes visible.
        mix_m = L.measure(mix)

        result = {
            "output": str(out_path),
            "master_bpm": master,
            "duration_s": round(len(mix) / SR, 1),
            "duration": f"{int(len(mix)/SR)//60}:{int(len(mix)/SR)%60:02d}",
            "crossfade_beats": xf_beats,
            "gain_match": {
                "mode": gain_match,
                "target_lufs": round(target, 1) if target is not None else None,
                "limit_db": gain_limit,
                "spread_lu": round(max(finite) - min(finite), 1) if finite else None,
                "clamped": clamped,
                "warnings": gain_warnings,
            },
            "mix": {
                "lufs_i": mix_m["lufs_i"],
                "lra": mix_m.get("lra"),
                "true_peak_dbfs": mix_m["true_peak_dbfs"],
                "peak_dbfs_before_normalise": round(peak_before_db, 2),
                "normalise_gain_db": round(norm_db, 2),
                "headroom_db": headroom_db,
            },
            "tracklist": tracklist,
        }
        # Carry the ordering rationale through from order.json. It used to be
        # hand-written into the tracklist and silently destroyed on every re-blend.
        if order.get("rationale"):
            result["order_rationale"] = order["rationale"]

    finally:
        # finally, not a trailing call: an early exit (every track refused)
        # must not leave a stretched copy of the set behind.
        if keep_staged:
            print(f"  staged files kept in {tmp}", file=sys.stderr)
            tmpdir._finalizer.detach()  # noqa: SLF001 -- deliberate
        else:
            tmpdir.cleanup()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--out", default="mix.wav")
    ap.add_argument("--gain-match", default="median",
                    help="'median' (default), 'off', or an absolute LUFS figure")
    ap.add_argument("--gain-limit", type=float, default=GAIN_LIMIT_DB,
                    help="max per-track correction in dB (default 3.0)")
    ap.add_argument("--headroom-db", type=float, default=-1.0,
                    help="peak-normalise the finished mix to this (default -1.0)")
    ap.add_argument("--keep-staged", action="store_true",
                    help="keep the stretched intermediates for debugging")
    args = ap.parse_args()

    order = json.loads(Path(args.order).read_text(encoding="utf-8"))
    result = blend(order, Path(args.out), gain_match=args.gain_match,
                   gain_limit=args.gain_limit, headroom_db=args.headroom_db,
                   keep_staged=args.keep_staged)
    Path(args.out).with_suffix(".tracklist.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
