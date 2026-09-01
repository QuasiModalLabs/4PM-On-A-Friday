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

Optional bilateral panning writes a SECOND file for headphones and leaves the
mix alone. It is off by default and it is not a mastering decision: width lives
in the audio, so a club PA hears whatever the file contains and no single
render can pan on phones while staying flat on speakers.

Usage:
    python3 blend.py --order order.json --out mix.wav
    python3 blend.py --order order.json --out mix.wav --bilateral 0.6

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


def box_lowpass(y: np.ndarray, sr: int, cutoff_hz: float,
                stages: int = 3) -> np.ndarray:
    """Zero-phase lowpass built from cascaded moving averages.

    numpy only, on purpose -- this skill has no scipy and is not getting one for
    a crossover. A centred box filter of length sr/cutoff has its first null at
    the cutoff; three of them cascade into a smooth enough rolloff and stay
    zero-phase, so the split does not smear the kick's transient.

    Precision matters here: the caller reconstructs the high band as y - lows,
    so a float32 cumsum over a ten-minute mix would accumulate visible error.
    Accumulate in float64 and cast once.

    Edge-padded, so the first and last ~n samples carry a settling transient.
    That is harmless on a mix that starts and ends in silence, and it keeps DC
    intact everywhere else -- which matters more, because the reconstruction
    identity depends on it.
    """
    n = max(1, int(round(sr / max(cutoff_hz, 1e-6))))
    n |= 1                      # odd window: pad symmetrically, so truly
    if n <= 1:                  # zero-phase rather than half a sample late
        return y.astype(np.float32, copy=True)
    out = y.astype(np.float64, copy=True)
    for _ in range(stages):
        pad = n // 2
        padded = np.pad(out, ((pad, pad), (0, 0)), mode="edge")
        c = np.cumsum(padded, axis=0, dtype=np.float64)
        c = np.concatenate([np.zeros((1, out.shape[1])), c], axis=0)
        out = (c[n:] - c[:-n]) / n
    return out.astype(np.float32)


def energy_envelope(y: np.ndarray, sr: int, smooth_hz: float = 0.5) -> np.ndarray:
    """Smoothed 0-1 loudness envelope, for deciding where the pan is welcome.

    Deliberately slow -- half a hertz, so it tracks the difference between a
    breakdown and a drop rather than following individual kicks. Gating on the
    kick itself would make the image flutter at 152 BPM, which is the opposite
    of the problem being solved.

    Scaled by the 95th percentile rather than the maximum: one transient should
    not define "loud" for the whole set.
    """
    mag = np.abs(y).mean(axis=1, keepdims=True).repeat(2, axis=1)
    env = box_lowpass(mag, sr, smooth_hz)[:, 0]
    p = float(np.percentile(env, 95))
    return np.clip(env / p, 0.0, 1.0) if p > 0 else np.zeros_like(env)


def bilateral_pan(y: np.ndarray, sr: int, bpm: float, depth: float, *,
                  beats_per_cycle: float = 4.0,
                  crossover_hz: float = 200.0,
                  gate: float = 0.0) -> np.ndarray:
    """Alternate the mix left/right at a bar rate, keeping the low end centred.

    depth is 0..1. At 0 this returns the input unchanged, exactly: the low band
    is untouched and the high band is multiplied by gains that are both 1.0, so
    lows + highs reconstructs the original sample for sample.

    Constant power, not constant amplitude. With m = depth*sin(2*pi*f*t), the
    gains are sqrt(1-m) and sqrt(1+m), whose squares sum to 2 at every instant.
    A linear pan would dip 3 dB through the centre once per cycle, which at a
    bar rate is an audible pulse rather than a pan.

    The low band never moves. Panning it is what destroys mono playback: the
    measured bass correlation of a full-mix pan is around 0.54, and
    loudness.mono_compat documents below ~0.9 as the point a system summing to
    a mono sub loses low end. Splitting at 200 Hz keeps that figure high while
    the rest of the mix still travels.
    """
    if depth <= 0.0:
        return y.astype(np.float32, copy=True)
    depth = float(min(depth, 1.0))
    lows = box_lowpass(y, sr, crossover_hz)
    highs = y.astype(np.float32) - lows

    # gate backs the swing off where the mix is already dense. Constant panning
    # is most objectionable through a drop -- there is no room for anything to
    # move -- and most welcome through a breakdown, where there is. At gate=1
    # the loudest passages sit dead centre and only the quiet ones travel.
    swing = depth
    if gate > 0.0:
        swing = depth * (1.0 - min(gate, 1.0) * energy_envelope(y, sr))

    f = (bpm / 60.0) / max(beats_per_cycle, 1e-6)
    t = np.arange(len(y), dtype=np.float64) / sr
    m = swing * np.sin(2.0 * np.pi * f * t)
    gains = np.stack([np.sqrt(1.0 - m), np.sqrt(1.0 + m)], axis=1)
    return (lows + highs * gains.astype(np.float32)).astype(np.float32)


def blend(order: dict, out_path: Path, *, gain_match: str = "median",
          gain_limit: float = GAIN_LIMIT_DB, headroom_db: float = -1.0,
          keep_staged: bool = False, bilateral: float = 0.0,
          bilateral_beats: float = 4.0,
          bilateral_crossover_hz: float = 200.0,
          bilateral_gate: float = 0.0) -> dict:
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

        # --- optional device mix -------------------------------------------
        # A SECOND file, never a replacement. Width is in the audio, so no
        # single render can pan on headphones and stay flat on a PA -- the club
        # hears whatever the file contains. mix.wav therefore stays exactly as
        # it was, and anything bilateral goes to mix.bilateral.wav for phones.
        if bilateral > 0.0:
            dev = bilateral_pan(mix, SR, master, bilateral,
                                beats_per_cycle=bilateral_beats,
                                crossover_hz=bilateral_crossover_hz,
                                gate=bilateral_gate)
            dev_peak = float(np.max(np.abs(dev))) if len(dev) else 1.0
            dev_norm_db = 0.0
            if dev_peak > 0:
                # The pan adds up to +3 dB on the loud side; re-normalise so the
                # two files sit at the same ceiling and can be compared by ear
                # without one flattering the other.
                dev_norm_db = headroom_db - L.lin_to_db(dev_peak)
                dev = dev * np.float32(L.db_to_lin(dev_norm_db))
            dev_path = out_path.with_suffix(".bilateral" + out_path.suffix)
            sf.write(str(dev_path), dev, SR, subtype="PCM_24")

            club_mono, dev_mono = L.mono_compat(mix), L.mono_compat(dev)
            dev_m = L.measure(dev)
            result["bilateral"] = {
                "output": str(dev_path),
                "depth": round(float(bilateral), 3),
                "beats_per_cycle": bilateral_beats,
                "rate_hz": round((master / 60.0) / bilateral_beats, 3),
                "crossover_hz": bilateral_crossover_hz,
                "gate": round(float(bilateral_gate), 3),
                "mean_applied_depth": round(float(np.mean(
                    bilateral * (1.0 - min(bilateral_gate, 1.0)
                                 * energy_envelope(mix, SR))
                    if bilateral_gate > 0 else bilateral)), 3),
                "normalise_gain_db": round(dev_norm_db, 2),
                "lufs_i": dev_m["lufs_i"],
                "true_peak_dbfs": dev_m["true_peak_dbfs"],
                "club_mix": {
                    "correlation": club_mono["correlation"],
                    "bass_correlation": club_mono["bass_correlation"],
                    "mono_sum_loss_lu": club_mono["mono_sum_loss_lu"],
                },
                "device_mix": {
                    "correlation": dev_mono["correlation"],
                    "bass_correlation": dev_mono["bass_correlation"],
                    "mono_sum_loss_lu": dev_mono["mono_sum_loss_lu"],
                },
                "note": ("headphone render; mix.wav is the one to play out. "
                         "Nothing here says it sounds better -- these are the "
                         "measured differences only."),
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
    ap.add_argument("--bilateral", type=float, default=0.0,
                    help="0-1 depth of bar-rate left/right panning. Off by "
                         "default. Writes an EXTRA <out>.bilateral.wav for "
                         "headphones; <out>.wav is untouched and stays the "
                         "one to play out.")
    ap.add_argument("--bilateral-beats", type=float, default=4.0,
                    help="beats per pan cycle (default 4, one bar)")
    ap.add_argument("--bilateral-crossover", type=float, default=200.0,
                    help="below this stays centred (default 200 Hz)")
    ap.add_argument("--bilateral-gate", type=float, default=0.0,
                    help="0-1: back the pan off where the mix is loud. 0 is "
                         "constant panning (default), 1 holds drops dead "
                         "centre and lets only breakdowns travel.")
    args = ap.parse_args()

    order = json.loads(Path(args.order).read_text(encoding="utf-8"))
    result = blend(order, Path(args.out), gain_match=args.gain_match,
                   gain_limit=args.gain_limit, headroom_db=args.headroom_db,
                   keep_staged=args.keep_staged, bilateral=args.bilateral,
                   bilateral_beats=args.bilateral_beats,
                   bilateral_crossover_hz=args.bilateral_crossover,
                   bilateral_gate=args.bilateral_gate)
    Path(args.out).with_suffix(".tracklist.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
