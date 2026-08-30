"""Shared setup for the test suite.

stdlib `unittest`, no pytest. Same reasoning that kept `pyloudnorm` out: this
repo holds six runtime dependencies on purpose, and a test runner that ships
with Python costs nothing to install on either platform.

    python -m unittest discover -s tests -v        (Windows)
    python3 -m unittest discover -s tests -v       (mac/Linux)

Signals are short (4 s) because ebur128 measures a 4 s buffer in about 60 ms;
the whole suite is dominated by the handful of tests that shell out repeatedly.
Nothing here is shorter than 3 s, which is where ebur128's integrated gate stops
being reliable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / ".claude" / "skills" / "hardstyle-blend" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import loudness as L  # noqa: E402
import master as M  # noqa: E402
import blend as B  # noqa: E402

SR = L.SR
SECS = 4.0

# The arithmetic anchor the whole suite leans on: a dual-mono 1 kHz sine of
# amplitude A measures exactly 20*log10(A) LUFS. The -3 dB sine RMS and the
# +3 dB dual-mono channel sum cancel, and K-weighting is ~0 dB at 1 kHz.
ANCHOR_AMP = 0.3535          # -9.0 dBFS
ANCHOR_LUFS = -9.0


def sine(amp=ANCHOR_AMP, secs=SECS, freq=1000.0, sr=SR):
    t = np.arange(int(sr * secs)) / sr
    s = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(s[:, None], 2, axis=1)


def noise(scale=0.05, secs=SECS, sr=SR, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((int(sr * secs), 2)) * scale).astype(np.float32)


def spiky(secs=SECS, sr=SR):
    """Quiet tone with full-scale transients -- forces the limiter to work."""
    y = sine(0.1, secs, sr=sr).copy()
    for i in range(1, int(secs)):
        y[sr * i:sr * i + 40] = 0.99
    return y


def short_term_crest(y, win=None, sr=SR):
    """Median half-second peak-to-RMS. On hardstyle this is the kick."""
    win = win or sr // 2
    a = np.abs(L.as_f32_stereo(y)).max(axis=1).astype(np.float64)
    k = (len(a) // win) * win
    if k == 0:
        return 0.0
    a = a[:k].reshape(-1, win)
    pk, rms = a.max(axis=1), np.sqrt((a ** 2).mean(axis=1))
    return float(np.median(20 * np.log10(pk / np.maximum(rms, 1e-12))))


def run_master(buf, **kw):
    """master() with the non-interesting arguments filled in."""
    kw.setdefault("target_lufs", -9.0)
    kw.setdefault("ceiling_dbfs", -1.0)
    kw.setdefault("limit_mode", "limit")
    kw.setdefault("eq_mode", "none")
    kw.setdefault("low_shelf_db", 0.0)
    kw.setdefault("high_shelf_db", 0.0)
    kw.setdefault("eq_limit", M.EQ_LIMIT)
    kw.setdefault("reference", None)
    kw.setdefault("do_mono", False)
    return M.master(buf, **kw)
