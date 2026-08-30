"""loudness.py -- measurement, gain staging, limiting, mono compatibility."""

import json
import unittest

import numpy as np

from _ctx import (ANCHOR_AMP, ANCHOR_LUFS, L, SR, noise, sine, spiky)


class TestConversions(unittest.TestCase):
    def test_db_lin_roundtrip(self):
        for db in (-60.0, -12.0, -1.0, 0.0, 6.0):
            self.assertAlmostEqual(L.lin_to_db(L.db_to_lin(db)), db, places=6)

    def test_known_values(self):
        self.assertAlmostEqual(L.db_to_lin(0.0), 1.0, places=9)
        self.assertAlmostEqual(L.db_to_lin(-6.0), 0.5011872, places=6)
        self.assertAlmostEqual(L.lin_to_db(0.5), -6.0206, places=3)

    def test_lin_to_db_floors_at_silence(self):
        # Must not return -inf or raise: a silent block is normal in a mix.
        self.assertLess(L.lin_to_db(0.0), -200.0)
        self.assertTrue(np.isfinite(L.lin_to_db(0.0)))


class TestBuffers(unittest.TestCase):
    def test_mono_is_duplicated_not_matrixed(self):
        # The 1/sqrt(2) energy-preserving matrix is exactly what we must avoid;
        # duplication keeps the level.
        mono = np.full((1000, 1), 0.5, dtype=np.float32)
        out = L.as_f32_stereo(mono)
        self.assertEqual(out.shape, (1000, 2))
        self.assertAlmostEqual(float(out.max()), 0.5, places=6)

    def test_1d_input_accepted(self):
        self.assertEqual(L.as_f32_stereo(np.zeros(500, dtype=np.float32)).shape,
                         (500, 2))

    def test_extra_channels_dropped(self):
        self.assertEqual(L.as_f32_stereo(np.zeros((10, 5), np.float32)).shape,
                         (10, 2))

    def test_output_is_contiguous_float32(self):
        out = L.as_f32_stereo(np.zeros((10, 2), np.float64))
        self.assertEqual(out.dtype, np.dtype("<f4"))
        self.assertTrue(out.flags["C_CONTIGUOUS"])


class TestParseEbur128(unittest.TestCase):
    SUMMARY = """
  Integrated loudness:
    I:         -11.4 LUFS
    Threshold: -21.5 LUFS

  Loudness range:
    LRA:         3.1 LU
    Threshold: -31.4 LUFS
    LRA low:   -13.0 LUFS
    LRA high:   -9.9 LUFS

  True peak:
    Peak:       -1.0 dBFS
"""

    def test_parses_all_fields(self):
        r = L.parse_ebur128(self.SUMMARY)
        self.assertAlmostEqual(r["lufs_i"], -11.4)
        self.assertAlmostEqual(r["lra"], 3.1)
        self.assertAlmostEqual(r["lra_low"], -13.0)
        self.assertAlmostEqual(r["lra_high"], -9.9)
        self.assertAlmostEqual(r["true_peak_dbfs"], -1.0)

    def test_threshold_taken_from_the_right_section(self):
        # "Threshold:" appears under BOTH Integrated and Loudness range. A flat
        # line regex silently picks the second one.
        self.assertAlmostEqual(L.parse_ebur128(self.SUMMARY)["threshold_lufs"], -21.5)

    def test_handles_negative_infinity(self):
        txt = self.SUMMARY.replace("-11.4 LUFS", "-inf LUFS")
        self.assertEqual(L.parse_ebur128(txt)["lufs_i"], float("-inf"))

    def test_handles_nan(self):
        txt = self.SUMMARY.replace("-11.4 LUFS", "nan LUFS")
        self.assertIsNone(L.parse_ebur128(txt)["lufs_i"])

    def test_raises_on_unparseable(self):
        # Must fail loudly. Defaulting to 0 dB would silently disable gain
        # matching and nobody would notice.
        with self.assertRaises(RuntimeError):
            L.parse_ebur128("ffmpeg: command not found")

    def test_raises_when_true_peak_missing(self):
        txt = self.SUMMARY.split("True peak:")[0]
        with self.assertRaises(RuntimeError):
            L.parse_ebur128(txt)


class TestMeasure(unittest.TestCase):
    def test_anchor(self):
        m = L.measure(sine())
        self.assertAlmostEqual(m["lufs_i"], ANCHOR_LUFS, delta=0.15)
        self.assertAlmostEqual(m["true_peak_dbfs"], ANCHOR_LUFS, delta=0.15)

    def test_amplitude_maps_to_lufs(self):
        for amp, want in ((0.1, -20.0), (0.5, -6.0), (0.9, -0.92)):
            with self.subTest(amp=amp):
                self.assertAlmostEqual(L.measure(sine(amp))["lufs_i"], want,
                                       delta=0.2)

    def test_sample_peak_reported(self):
        m = L.measure(sine(0.5))
        self.assertAlmostEqual(m["sample_peak_dbfs"], -6.0, delta=0.1)

    def test_duration_reported(self):
        self.assertAlmostEqual(L.measure(sine(secs=4.0))["duration_s"], 4.0,
                               delta=0.01)

    def test_short_buffer_flagged(self):
        # Below ~3 s the integrated gate may never open; callers need to know.
        self.assertTrue(L.measure(sine(secs=1.0)).get("short"))
        self.assertNotIn("short", L.measure(sine(secs=4.0)))

    def test_gain_is_exact(self):
        base = L.measure(sine())["lufs_i"]
        for g in (-6.0, -1.0, 3.0, 6.0):
            with self.subTest(gain=g):
                got = L.measure(L.apply_gain(sine(), g))["lufs_i"]
                self.assertAlmostEqual(got, base + g, delta=0.15)


class TestFilterPipe(unittest.TestCase):
    def test_pipe_is_level_transparent(self):
        # Unpinned -ar/-ac lets ffmpeg insert a channel matrix worth -3 dB.
        m = L.measure(L.ffmpeg_filter(sine(), "anull"))
        self.assertAlmostEqual(m["lufs_i"], ANCHOR_LUFS, delta=0.15)

    def test_pipe_preserves_shape(self):
        y = sine()
        self.assertEqual(L.ffmpeg_filter(y, "anull").shape, y.shape)

    def test_bad_filter_raises(self):
        with self.assertRaises(RuntimeError):
            L.ffmpeg_filter(sine(), "definitelynotafilter=1")

    def test_low_shelf_lifts_the_low_bands(self):
        # Asserted on band energy, not LUFS: K-weighting de-emphasises bass, so
        # a low shelf barely moves the integrated figure even when it is clearly
        # audible.
        flat = L.band_profile(noise())
        lifted = L.band_profile(L.apply_shelves(noise(), 3.0, 0.0))
        self.assertGreater(lifted["sub"] - flat["sub"], 1.0)
        self.assertGreater(lifted["low"] - flat["low"], 0.5)

    def test_high_shelf_lifts_the_top(self):
        flat = L.band_profile(noise())
        lifted = L.band_profile(L.apply_shelves(noise(), 0.0, 3.0))
        self.assertGreater(lifted["air"] - flat["air"], 1.0)

    def test_shelves_are_signed_correctly(self):
        flat = L.band_profile(noise())
        cut = L.band_profile(L.apply_shelves(noise(), -3.0, 0.0))
        self.assertLess(cut["sub"] - flat["sub"], -1.0)

    def test_zero_shelves_are_a_noop(self):
        y = sine()
        np.testing.assert_allclose(L.apply_shelves(y, 0.0, 0.0), y, atol=1e-7)


class TestLatency(unittest.TestCase):
    def test_zero_delay(self):
        y = spiky()
        self.assertEqual(L.estimate_latency(y[:, 0], y[:, 0]), 0)

    def test_known_synthetic_delay(self):
        y = spiky()
        for lag in (37, 219, 777):
            with self.subTest(lag=lag):
                d = np.concatenate([np.zeros(lag, np.float32), y[:, 0]])[:len(y)]
                self.assertEqual(L.estimate_latency(y[:, 0], d), lag)

    def test_detects_alimiter_lookahead(self):
        # alimiter delays by its attack time. Without correcting for it, the
        # gain-reduction figure compares two different moments and inflates.
        y = spiky()
        raw = L.ffmpeg_filter(
            y, "alimiter=level_in=1:level_out=1:limit=0.891:attack=5"
               ":release=50:level=disabled")
        self.assertAlmostEqual(L.estimate_latency(y[:, 0], raw[:, 0]), 219,
                               delta=4)

    def test_silence_returns_zero(self):
        z = np.zeros(10000, np.float32)
        self.assertEqual(L.estimate_latency(z, z), 0)


class TestLimiter(unittest.TestCase):
    def test_holds_the_sample_ceiling(self):
        out, _ = L.apply_limiter(L.apply_gain(spiky(), 6.0), -1.0)
        self.assertLessEqual(L.measure(out)["sample_peak_dbfs"], -1.0 + 0.05)

    def test_does_not_auto_level(self):
        # alimiter's `level` defaults to true and would gain the output back up
        # to the ceiling, discarding the gain computed upstream.
        quiet = sine(0.02)
        out, _ = L.apply_limiter(quiet, -1.0)
        self.assertAlmostEqual(L.measure(out)["lufs_i"],
                               L.measure(quiet)["lufs_i"], delta=0.3)

    def test_reports_gain_reduction(self):
        _, lim = L.apply_limiter(L.apply_gain(spiky(), 6.0), -1.0)
        self.assertTrue(lim["engaged"])
        self.assertLess(lim["gr_max_db"], 0.0)
        self.assertGreater(lim["limited_pct"], 0.0)
        self.assertLessEqual(lim["limited_pct"], 100.0)

    def test_reports_latency_it_compensated(self):
        _, lim = L.apply_limiter(spiky(), -1.0)
        self.assertGreater(lim["latency_samples"], 0)

    def test_output_is_length_aligned_with_input(self):
        y = spiky()
        out, _ = L.apply_limiter(y, -1.0)
        self.assertEqual(len(out), len(y))

    def test_latency_compensation_keeps_transients_in_place(self):
        # The master must stay sample-aligned with the mix, or tracklist
        # timestamps drift against the audio.
        y = spiky()
        out, _ = L.apply_limiter(y, -1.0)
        self.assertLessEqual(abs(L.estimate_latency(y[:, 0], out[:, 0])), 4)

    def test_untouched_signal_reports_near_zero_reduction(self):
        _, lim = L.apply_limiter(sine(0.05), -1.0)
        self.assertLess(lim["limited_pct"], 1.0)


class TestBands(unittest.TestCase):
    def test_band_energy_has_every_band(self):
        r = L.band_energy_db(noise())
        for name, _, _ in L.BANDS:
            self.assertIn(name, r)
            self.assertIn(name + "_rel", r)

    def test_tone_lands_in_the_right_band(self):
        r = L.band_energy_db(sine(freq=8000.0))
        loudest = max((n for n, _, _ in L.BANDS), key=lambda n: r[n + "_rel"])
        self.assertEqual(loudest, "air")

    def test_profile_is_level_independent(self):
        # Shape, not level: a louder reference must not read as wanting a boost.
        a = L.band_profile(noise())
        b = L.band_profile(L.apply_gain(noise(), 9.0))
        for k in a:
            self.assertAlmostEqual(a[k], b[k], delta=0.05)

    def test_profile_is_mean_normalised(self):
        vals = list(L.band_profile(noise()).values())
        self.assertAlmostEqual(float(np.mean(vals)), 0.0, delta=0.05)

    def test_white_noise_rises_per_octave(self):
        # White noise has equal energy per Hz, so per octave it climbs.
        p = L.band_profile(noise())
        self.assertGreater(p["air"], p["sub"])


class TestMonoCompat(unittest.TestCase):
    def test_dual_mono(self):
        r = L.mono_compat(sine())
        self.assertAlmostEqual(r["correlation"], 1.0, delta=0.02)
        self.assertAlmostEqual(r["mono_sum_loss_lu"], 0.0, delta=0.15)
        self.assertEqual(r["warnings"], [])

    def test_decorrelated_loses_about_three(self):
        r = L.mono_compat(noise())
        self.assertAlmostEqual(r["correlation"], 0.0, delta=0.05)
        self.assertAlmostEqual(r["mono_sum_loss_lu"], -3.0, delta=0.4)

    def test_inverted_collapses(self):
        s = sine()
        r = L.mono_compat(np.stack([s[:, 0], -s[:, 0]], axis=1))
        self.assertAlmostEqual(r["correlation"], -1.0, delta=0.02)
        self.assertLess(r["mono_sum_loss_lu"], -20.0)

    def test_bass_correlation_warns(self):
        r = L.mono_compat(noise())
        self.assertTrue(any("bass correlation" in w for w in r["warnings"]))

    def test_report_is_json_serialisable(self):
        json.dumps(L.mono_compat(sine()))


if __name__ == "__main__":
    unittest.main()
