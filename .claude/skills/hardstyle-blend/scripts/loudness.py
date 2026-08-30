#!/usr/bin/env python3
"""Loudness measurement and gain staging. Shared by blend.py and master.py.

Measurement is ffmpeg's ebur128 -- the EBU R128 reference implementation.
One pass gives integrated LUFS, loudness range and 4x-oversampled true peak,
and it alters nothing (it is an A->N filter; with -f null - it writes no audio).

Gain is applied in numpy. A scalar multiply is exact and reportable to two
decimals; round-tripping a 180 MB buffer through ffmpeg to multiply by a
constant buys nothing.

ffmpeg's loudnorm filter is deliberately NOT used, and should not be
reintroduced as a simplification. It resamples to 192 kHz internally -- verified
on this build: 44100 Hz in, 192000 Hz out. This pipeline does not resample; see
the timestretch rule in CLAUDE.md. ebur128, alimiter, bass and treble all run at
the input rate.

Two ffmpeg behaviours this module exists to contain:

  * alimiter's `level` option defaults to TRUE, which auto-gains the output back
    up to the ceiling and would silently discard the gain just computed.
    apply_limiter always passes level=disabled.
  * An implicit mono->stereo upmix applies the energy-preserving 1/sqrt(2)
    matrix -- a hidden -3 dB. Every pipe pins -f f32le -ar/-ac on BOTH sides so
    no implicit conversion is ever chosen for us.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

SR = 44100

# Wide bands, chosen to be legible rather than precise. Reported relative to the
# file's own total, so comparing two files does not turn a level difference into
# an apparent tonal one.
BANDS = [
    ("sub", 20, 60),
    ("low", 60, 150),
    ("lowmid", 150, 400),
    ("mid", 400, 2000),
    ("highmid", 2000, 6000),
    ("air", 6000, 16000),
]

# ebur128's integrated measurement is gated; below a few seconds the gate may
# never open and I comes back -inf.
MIN_RELIABLE_S = 3.0


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def lin_to_db(x) -> float:
    return float(20.0 * np.log10(np.maximum(x, 1e-12)))


def as_f32_stereo(buf: np.ndarray) -> np.ndarray:
    """Contiguous float32 (n, 2). Mono is duplicated, never matrixed."""
    y = np.asarray(buf, dtype=np.float32)
    if y.ndim == 1:
        y = y[:, None]
    if y.shape[1] == 1:
        y = np.repeat(y, 2, axis=1)
    return np.ascontiguousarray(y[:, :2], dtype="<f4")


def _run(cmd, payload=None):
    # subprocess.run(input=...) rather than manual Popen writes: a 110 MB write
    # to a pipe nobody is draining will deadlock.
    return subprocess.run(cmd, input=payload, capture_output=True)


def parse_ebur128(stderr_text: str) -> dict:
    """Parse the Summary block.

    Parsed by section, not by a flat line regex, because "Threshold:" appears
    under BOTH "Integrated loudness:" and "Loudness range:" -- a flat regex
    silently picks the wrong one.
    """
    out = {}
    section = None

    def num(line):
        m = re.search(r"(-?inf|nan|-?\d+(?:\.\d+)?)", line)
        if not m:
            return None
        tok = m.group(1)
        if tok == "nan":
            return None
        if tok.endswith("inf"):
            return float("-inf") if tok.startswith("-") else float("inf")
        return float(tok)

    for raw in stderr_text.splitlines():
        line = raw.strip()
        if line.startswith("Integrated loudness"):
            section = "i"
        elif line.startswith("Loudness range"):
            section = "lra"
        elif line.startswith("True peak"):
            section = "tp"
        elif section == "i" and line.startswith("I:"):
            out["lufs_i"] = num(line)
        elif section == "i" and line.startswith("Threshold:"):
            out["threshold_lufs"] = num(line)
        elif section == "lra" and line.startswith("LRA:"):
            out["lra"] = num(line)
        elif section == "lra" and line.startswith("LRA low:"):
            out["lra_low"] = num(line)
        elif section == "lra" and line.startswith("LRA high:"):
            out["lra_high"] = num(line)
        elif section == "tp" and line.startswith("Peak:"):
            out["true_peak_dbfs"] = num(line)

    missing = {"lufs_i", "true_peak_dbfs"} - out.keys()
    if missing:
        tail = "\n".join(stderr_text.strip().splitlines()[-15:])
        raise RuntimeError(
            "could not parse ebur128 output (missing %s).\n%s"
            % (sorted(missing), tail))
    return out


def _ebur128(cmd_input, payload):
    cmd = ["ffmpeg", "-hide_banner", "-nostats", *cmd_input,
           "-filter_complex", "ebur128=peak=true", "-f", "null", "-"]
    p = _run(cmd, payload)
    return parse_ebur128(p.stderr.decode("utf-8", "replace"))


def measure(buf: np.ndarray, sr: int = SR) -> dict:
    """Measure an in-memory stereo float32 buffer."""
    y = as_f32_stereo(buf)
    dur = len(y) / sr
    m = _ebur128(["-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-"], y.tobytes())
    m["duration_s"] = round(dur, 2)
    m["sample_peak_dbfs"] = round(
        lin_to_db(np.max(np.abs(y))) if len(y) else -240.0, 2)
    if dur < MIN_RELIABLE_S:
        m["short"] = True
    return m


def measure_file(path: Path, sr: int = SR) -> dict:
    m = _ebur128(["-i", str(path)], None)
    try:
        import soundfile as sf
        info = sf.info(str(path))
        m["duration_s"] = round(info.frames / info.samplerate, 2)
        if m["duration_s"] < MIN_RELIABLE_S:
            m["short"] = True
    except Exception:
        pass
    return m


def ffmpeg_filter(buf: np.ndarray, filter_str: str, sr: int = SR) -> np.ndarray:
    """Carry audio through one ffmpeg filter chain, raw float32 both ways.

    -f/-ar/-ac pinned on input AND output. Unpinned, ffmpeg is free to insert a
    channel-matrix or resample step that quietly changes the level.
    """
    y = as_f32_stereo(buf)
    cmd = ["ffmpeg", "-hide_banner", "-nostats",
           "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-",
           "-filter:a", filter_str,
           "-f", "f32le", "-ar", str(sr), "-ac", "2", "-"]
    p = _run(cmd, y.tobytes())
    if p.returncode != 0:
        tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-10:]
        raise RuntimeError(
            "ffmpeg filter failed (%s):\n%s" % (filter_str, "\n".join(tail)))
    out = np.frombuffer(p.stdout, dtype="<f4")
    return out.reshape(-1, 2).astype(np.float32, copy=True)


def apply_gain(buf: np.ndarray, gain_db: float) -> np.ndarray:
    return (as_f32_stereo(buf) * np.float32(db_to_lin(gain_db))).astype(np.float32)


def _block_env(x: np.ndarray, block: int = 1024) -> np.ndarray:
    n = (len(x) // block) * block
    if n == 0:
        return np.array([np.max(np.abs(x))] if len(x) else [0.0])
    return np.abs(x[:n]).reshape(-1, block).max(axis=1)


def estimate_latency(x: np.ndarray, y: np.ndarray, max_lag: int = 4096) -> int:
    """Sample delay of y relative to x, by FFT cross-correlation on a window.

    alimiter is a look-ahead limiter and delays its output by the attack time
    (measured: 219 samples at attack=5ms/44.1k). Comparing envelopes without
    correcting for that compares two different moments and reports gain
    reduction that never happened.
    """
    n = min(len(x), len(y), 1 << 18)
    if n < 1024:
        return 0
    a = np.asarray(x[:n], dtype=np.float64)
    b = np.asarray(y[:n], dtype=np.float64)
    a = a - a.mean()
    b = b - b.mean()
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return 0
    size = 1 << int(np.ceil(np.log2(2 * n)))
    c = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    cand = np.concatenate([c[:max_lag + 1], c[-max_lag:]])
    idx = int(np.argmax(cand))
    return idx if idx <= max_lag else idx - (max_lag + 1) - max_lag


def apply_limiter(buf: np.ndarray, ceiling_dbfs: float, sr: int = SR,
                  attack_ms: float = 5.0, release_ms: float = 50.0):
    """Look-ahead limit to a ceiling, and measure what it actually did.

    alimiter does not report gain reduction, so it is computed here by comparing
    input and output envelopes -- latency-aligned first. "The limiter touched
    3.1% of the file, worst case -1.4 dB" is auditable; "the limiter ran" is not.

    The output is also latency-compensated, so the master stays sample-aligned
    with the mix it came from and the tracklist timestamps stay true.
    """
    y = as_f32_stereo(buf)
    limit = db_to_lin(ceiling_dbfs)
    # level=disabled is mandatory: the default (true) auto-levels the output back
    # up to the ceiling, silently discarding the gain computed upstream.
    raw = ffmpeg_filter(
        y,
        "alimiter=level_in=1:level_out=1:limit=%.6f:attack=%g:release=%g"
        ":level=disabled" % (limit, attack_ms, release_ms),
        sr,
    )

    lat = max(0, estimate_latency(y[:, 0], raw[:, 0]))
    if lat:
        out = raw[lat:]
        if len(out) < len(y):
            out = np.concatenate(
                [out, np.zeros((len(y) - len(out), 2), dtype=np.float32)], axis=0)
    else:
        out = raw
    out = out[:len(y)]

    n = min(len(y), len(out))
    env_in = _block_env(np.abs(y[:n]).max(axis=1))
    env_out = _block_env(np.abs(out[:n]).max(axis=1))
    k = min(len(env_in), len(env_out))
    # Only count blocks where there is signal to reduce; a near-silent block
    # divides two tiny numbers and reports nonsense.
    live = env_in[:k] > db_to_lin(-60.0)
    gr = np.zeros(k)
    gr[live] = 20.0 * np.log10(
        np.maximum(env_out[:k][live], 1e-12) / np.maximum(env_in[:k][live], 1e-12))
    touched = gr < -0.05
    return out, {
        "engaged": True,
        "ceiling_dbfs": round(ceiling_dbfs, 2),
        "latency_samples": int(lat),
        "gr_max_db": round(float(gr.min()), 2) if k else 0.0,
        "gr_mean_db": round(float(gr[touched].mean()), 2) if touched.any() else 0.0,
        "limited_pct": round(float(touched.mean() * 100.0), 2) if k else 0.0,
    }


def apply_shelves(buf, low_db: float, high_db: float, sr: int = SR) -> np.ndarray:
    """Broad low and high shelves. IIR at the input rate; no resampling."""
    parts = []
    if abs(low_db) >= 0.01:
        parts.append("bass=g=%.2f:f=120:width_type=q:w=0.7" % low_db)
    if abs(high_db) >= 0.01:
        parts.append("treble=g=%.2f:f=8000:width_type=q:w=0.7" % high_db)
    if not parts:
        return as_f32_stereo(buf)
    return ffmpeg_filter(buf, ",".join(parts), sr)


FFT_N = 8192
FFT_HOP = 4096


def _avg_spectrum(buf: np.ndarray, sr: int = SR):
    """Mean power spectrum, block-accumulated.

    Block-accumulated rather than one big rfft: an 11-minute file is 30M samples
    and a full-length complex spectrum is half a gigabyte for no benefit.
    """
    mono = as_f32_stereo(buf).mean(axis=1)
    n, hop = FFT_N, FFT_HOP
    if len(mono) < n:
        mono = np.pad(mono, (0, n - len(mono)))
    win = np.hanning(n).astype(np.float32)
    acc = np.zeros(n // 2 + 1, dtype=np.float64)
    frames = 0
    for i in range(0, len(mono) - n + 1, hop):
        acc += np.abs(np.fft.rfft(mono[i:i + n] * win)) ** 2
        frames += 1
    if frames:
        acc /= frames
    return acc, np.fft.rfftfreq(n, 1.0 / sr), frames


def band_energy_db(buf: np.ndarray, sr: int = SR) -> dict:
    """Mean power per band, in dB, absolute and relative to the file's total."""
    acc, freqs, frames = _avg_spectrum(buf, sr)
    total = acc.sum()
    out = {"frames": frames}
    for name, lo, hi in BANDS:
        p = float(acc[(freqs >= lo) & (freqs < hi)].sum())
        out[name] = round(lin_to_db(np.sqrt(p)), 2)
        out[name + "_rel"] = (
            round(10.0 * np.log10(p / total + 1e-15), 2) if total else -240.0)
    return out


def band_centers() -> dict:
    """Geometric centre and octave span of each band."""
    return {name: (float(np.sqrt(lo * hi)), float(np.log2(hi / lo)))
            for name, lo, hi in BANDS}


def band_profile(buf: np.ndarray, sr: int = SR) -> dict:
    """Pink-referenced per-octave band levels, mean-normalised.

    Per OCTAVE, not per band. A raw band sum is dominated by how wide the band
    is -- 6-16 kHz spans eight times the span of 20-60 Hz and outweighs it
    whatever the tilt, which makes a raw-sum comparison against a tilt curve
    meaningless. Mastering's "dB per octave" is slope relative to pink noise,
    and pink noise is equal energy per octave, so per-octave is the comparable
    quantity.

    Mean-normalised so this describes SHAPE, not level: a louder reference must
    not read as wanting a broadband boost.
    """
    acc, freqs, _ = _avg_spectrum(buf, sr)
    centers = band_centers()
    vals = {}
    for name, lo, hi in BANDS:
        p = float(acc[(freqs >= lo) & (freqs < hi)].sum())
        vals[name] = 10.0 * np.log10(p / centers[name][1] + 1e-20)
    mean = float(np.mean(list(vals.values())))
    return {k: round(v - mean, 2) for k, v in vals.items()}


def mono_compat(buf: np.ndarray, sr: int = SR) -> dict:
    """Stereo/mono correlation and the level lost when summed to mono.

    Reference points for mono_sum_loss_lu:
       0.0   fully correlated (dual mono)
      -3.0   fully decorrelated stereo -- normal, fine
      -6.0   significant cancellation
      large negative / -inf   L is roughly -R, broken

    bass_correlation is the one that decides club playback: below ~0.9 in
    20-150 Hz, a system summing to a mono sub loses low end.
    """
    y = as_f32_stereo(buf)
    L, R = y[:, 0].astype(np.float64), y[:, 1].astype(np.float64)

    def corr(a, b):
        if len(a) < 2 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
            return None
        return round(float(np.corrcoef(a, b)[0, 1]), 3)

    def sum_loss(stereo):
        m = ((stereo[:, 0].astype(np.float64) + stereo[:, 1].astype(np.float64))
             * 0.5).astype(np.float32)
        dual = np.repeat(m[:, None], 2, axis=1)
        a = measure(dual, sr)["lufs_i"]
        b = measure(stereo, sr)["lufs_i"]
        if a is None or b is None or not (np.isfinite(a) and np.isfinite(b)):
            return None
        return round(a - b, 2)

    bass = ffmpeg_filter(y, "lowpass=f=150", sr)
    rep = {
        "correlation": corr(L, R),
        "bass_correlation": corr(bass[:, 0].astype(np.float64),
                                 bass[:, 1].astype(np.float64)),
        "mono_sum_loss_lu": sum_loss(y),
        "bass_mono_sum_loss_lu": sum_loss(bass),
    }
    warns = []
    if rep["bass_correlation"] is not None and rep["bass_correlation"] < 0.9:
        warns.append(
            "bass correlation %.2f is below 0.9: a club system summing to a mono "
            "sub will lose low end" % rep["bass_correlation"])
    if rep["mono_sum_loss_lu"] is not None and rep["mono_sum_loss_lu"] < -6.0:
        warns.append(
            "mono sum loses %.1f LU: significant phase cancellation"
            % abs(rep["mono_sum_loss_lu"]))
    rep["warnings"] = warns
    return rep
