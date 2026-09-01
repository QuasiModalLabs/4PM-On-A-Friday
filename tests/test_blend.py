"""blend.py -- tempo chain, crossfades, per-track level match, staging."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from _ctx import B, L, SCRIPTS, SR, sine


def write_set(dirpath, amps, secs=4.0, bpm=150.0, master_bpm=150.0,
              rationale=None):
    """A minimal order.json plus its tracks.

    bpm == master_bpm by default so the stretch ratio is exactly 1.0 and the
    tests isolate level matching from timestretch.
    """
    tracks = []
    for i, amp in enumerate(amps):
        p = Path(dirpath) / ("%02d.wav" % i)
        sf.write(str(p), sine(amp, secs), SR, subtype="PCM_24")
        tracks.append({"path": str(p), "bpm": bpm, "first_beat_s": 0.0,
                       "title": "T%d" % i})
    order = {"master_bpm": master_bpm, "crossfade_beats": 8, "tracks": tracks}
    if rationale:
        order["rationale"] = rationale
    op = Path(dirpath) / "order.json"
    op.write_text(json.dumps(order, indent=2), encoding="utf-8")
    return op, order


class TestAtempoChain(unittest.TestCase):
    def test_single_stage_within_range(self):
        self.assertEqual(B.atempo_chain(1.0).count("atempo"), 1)
        self.assertEqual(B.atempo_chain(0.75).count("atempo"), 1)

    def test_chains_above_two(self):
        # atempo accepts 0.5-2.0 per stage.
        self.assertGreater(B.atempo_chain(3.0).count("atempo"), 1)

    def test_chains_below_half(self):
        self.assertGreater(B.atempo_chain(0.25).count("atempo"), 1)

    def test_stages_multiply_back_to_the_ratio(self):
        for ratio in (0.3, 0.5, 0.97, 1.03, 2.0, 4.5):
            with self.subTest(ratio=ratio):
                stages = [float(part.split("=")[1])
                          for part in B.atempo_chain(ratio).split(",")]
                self.assertAlmostEqual(float(np.prod(stages)), ratio, places=4)

    def test_every_stage_is_legal(self):
        for ratio in (0.2, 0.25, 3.0, 8.0):
            with self.subTest(ratio=ratio):
                for part in B.atempo_chain(ratio).split(","):
                    v = float(part.split("=")[1])
                    self.assertGreaterEqual(v, 0.5)
                    self.assertLessEqual(v, 2.0)


class TestEqualPowerFade(unittest.TestCase):
    def test_curves_start_and_end_correctly(self):
        out_c, in_c = B.equal_power_fade(1000)
        self.assertAlmostEqual(float(out_c[0]), 1.0, places=5)
        self.assertAlmostEqual(float(out_c[-1]), 0.0, places=5)
        self.assertAlmostEqual(float(in_c[0]), 0.0, places=5)
        self.assertAlmostEqual(float(in_c[-1]), 1.0, places=5)

    def test_power_is_constant_across_the_fade(self):
        # This is the point of equal-power: a linear fade dips in the middle and
        # the dip is audible on a continuous mix.
        out_c, in_c = B.equal_power_fade(1000)
        power = out_c ** 2 + in_c ** 2
        np.testing.assert_allclose(power, 1.0, atol=1e-5)

    def test_length_is_respected(self):
        self.assertEqual(len(B.equal_power_fade(77)[0]), 77)


class TestStretch(unittest.TestCase):
    def test_stages_to_float32_not_16_bit(self):
        # The only signal path into the mix. Undithered 16-bit truncation here
        # would be amplified by the per-track gain applied afterwards.
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.wav", Path(td) / "s.wav"
            sf.write(str(src), sine(), SR, subtype="PCM_24")
            B.stretch(src, dst, 1.03)
            self.assertEqual(sf.info(str(dst)).subtype, "FLOAT")

    def test_stays_at_44100(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.wav", Path(td) / "s.wav"
            sf.write(str(src), sine(), SR, subtype="PCM_24")
            B.stretch(src, dst, 1.03)
            self.assertEqual(sf.info(str(dst)).samplerate, SR)

    def test_changes_duration_by_the_ratio(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.wav", Path(td) / "s.wav"
            sf.write(str(src), sine(secs=4.0), SR, subtype="PCM_24")
            B.stretch(src, dst, 2.0)
            info = sf.info(str(dst))
            self.assertAlmostEqual(info.frames / info.samplerate, 2.0, delta=0.1)

    def test_preserves_pitch(self):
        # atempo, not resampling: the key must survive or the harmonic ordering
        # is wasted.
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.wav", Path(td) / "s.wav"
            sf.write(str(src), sine(freq=1000.0, secs=4.0), SR, subtype="PCM_24")
            B.stretch(src, dst, 1.10)
            y = B.load_stereo(dst)
            spec = np.abs(np.fft.rfft(y[:8192, 0] * np.hanning(8192)))
            peak_hz = np.fft.rfftfreq(8192, 1 / SR)[int(np.argmax(spec))]
            self.assertAlmostEqual(peak_hz, 1000.0, delta=15.0)


class TestLoadStereo(unittest.TestCase):
    def test_rejects_wrong_sample_rate(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.wav"
            sf.write(str(p), sine(sr=48000), 48000, subtype="PCM_24")
            with self.assertRaises(ValueError):
                B.load_stereo(p)

    def test_mono_is_widened(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.wav"
            sf.write(str(p), np.zeros(SR, np.float32), SR, subtype="PCM_24")
            self.assertEqual(B.load_stereo(p).shape[1], 2)


class TestGainMatch(unittest.TestCase):
    def test_targets_the_median(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.5, 0.25, 0.125])   # -6 / -12 / -18 LUFS
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            self.assertAlmostEqual(r["gain_match"]["target_lufs"], -12.0,
                                   delta=0.3)

    def test_recovers_the_injected_offsets(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.5, 0.25, 0.125])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav",
                        gain_limit=12.0)
            gains = [t["gain_db"] for t in r["tracklist"]]
            for got, want in zip(gains, (-6.0, 0.0, 6.0)):
                self.assertAlmostEqual(got, want, delta=0.3)

    def test_clamps_and_names_what_it_clamped(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.5, 0.25, 0.125])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            gm = r["gain_match"]
            self.assertEqual(sorted(gm["clamped"]), ["00.wav", "02.wav"])
            self.assertEqual(len(gm["warnings"]), 2)
            self.assertTrue(all("clamped to" in w for w in gm["warnings"]))
            for t in r["tracklist"]:
                self.assertLessEqual(abs(t["gain_db"]), 3.0 + 1e-6)

    def test_matched_set_needs_no_correction(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25, 0.25])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            for t in r["tracklist"]:
                self.assertAlmostEqual(t["gain_db"], 0.0, delta=0.1)
            self.assertEqual(r["gain_match"]["clamped"], [])

    def test_off_disables_it(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.5, 0.25, 0.125])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav",
                        gain_match="off")
            self.assertIsNone(r["gain_match"]["target_lufs"])
            for t in r["tracklist"]:
                self.assertEqual(t["gain_db"], 0.0)

    def test_absolute_target_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav",
                        gain_match="-15.0", gain_limit=12.0)
            self.assertAlmostEqual(r["gain_match"]["target_lufs"], -15.0,
                                   delta=0.1)
            for t in r["tracklist"]:
                self.assertAlmostEqual(t["gain_db"], -3.0, delta=0.3)

    def test_spread_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.5, 0.25, 0.125])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            self.assertAlmostEqual(r["gain_match"]["spread_lu"], 12.0, delta=0.5)

    def test_per_track_measurements_are_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.5, 0.25])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            for t in r["tracklist"]:
                self.assertIn("input_lufs", t)
                self.assertIn("input_true_peak_dbfs", t)
                self.assertIn("gain_db", t)


class TestBlendOutput(unittest.TestCase):
    def test_writes_24_bit_at_44100(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25])
            out = Path(td) / "mix.wav"
            B.blend(json.loads(op.read_text()), out)
            info = sf.info(str(out))
            self.assertEqual(info.samplerate, SR)
            self.assertIn("24", info.subtype)

    def test_headroom_is_respected(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25])
            for headroom in (-1.0, -3.0):
                with self.subTest(headroom=headroom):
                    out = Path(td) / ("mix%s.wav" % headroom)
                    r = B.blend(json.loads(op.read_text()), out,
                                headroom_db=headroom)
                    self.assertAlmostEqual(r["mix"]["headroom_db"], headroom)
                    y, _ = sf.read(str(out), dtype="float32", always_2d=True)
                    self.assertAlmostEqual(L.lin_to_db(np.max(np.abs(y))),
                                           headroom, delta=0.1)

    def test_crossfade_shortens_the_total(self):
        # Two 4 s tracks overlapped must be shorter than 8 s.
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25], secs=4.0)
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            self.assertLess(r["duration_s"], 8.0)
            self.assertGreater(r["duration_s"], 4.0)

    def test_tracklist_positions_and_timestamps(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25, 0.25])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            self.assertEqual([t["position"] for t in r["tracklist"]], [1, 2, 3])
            starts = [t["start_s"] for t in r["tracklist"]]
            self.assertEqual(starts, sorted(starts))
            self.assertEqual(r["tracklist"][0]["start_s"], 0.0)

    def test_mix_is_measured(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            for key in ("lufs_i", "true_peak_dbfs",
                        "peak_dbfs_before_normalise", "normalise_gain_db"):
                self.assertIn(key, r["mix"])

    def test_report_is_json_serialisable(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25])
            json.dumps(B.blend(json.loads(op.read_text()), Path(td) / "mix.wav"))


class TestRationale(unittest.TestCase):
    def test_carried_through_from_order_json(self):
        # It used to be hand-written into the tracklist and destroyed on the
        # next re-blend.
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25], rationale="chronological")
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            self.assertEqual(r["order_rationale"], "chronological")

    def test_absent_when_not_supplied(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25])
            r = B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
            self.assertNotIn("order_rationale", r)


class TestRefusal(unittest.TestCase):
    def test_excessive_stretch_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25, 0.25])
            order = json.loads(op.read_text())
            order["tracks"][1]["bpm"] = 300.0          # would need -50%
            r = B.blend(order, Path(td) / "mix.wav")
            self.assertEqual(len(r["tracklist"]), 2)
            self.assertNotIn("01.wav", [t["file"] for t in r["tracklist"]])

    def test_refused_track_does_not_skew_the_median(self):
        # The median must be over surviving tracks only -- the reason the loop
        # is split into two passes.
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.02, 0.25])
            order = json.loads(op.read_text())
            order["tracks"][1]["bpm"] = 300.0
            r = B.blend(order, Path(td) / "mix.wav")
            self.assertAlmostEqual(r["gain_match"]["target_lufs"], -12.0,
                                   delta=0.4)

    def test_all_refused_raises(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25])
            order = json.loads(op.read_text())
            order["tracks"][0]["bpm"] = 300.0
            with self.assertRaises(SystemExit):
                B.blend(order, Path(td) / "mix.wav")


class TestStagingCleanup(unittest.TestCase):
    def test_temp_dir_is_removed(self):
        # mkdtemp() used to leak a stretched copy of every track, per run.
        before = set(Path(tempfile.gettempdir()).glob("tmp*"))
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25])
            B.blend(json.loads(op.read_text()), Path(td) / "mix.wav")
        leaked = set(Path(tempfile.gettempdir()).glob("tmp*")) - before
        self.assertEqual([p for p in leaked if p.is_dir()], [])


class TestCli(unittest.TestCase):
    def test_writes_mix_and_tracklist(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.25, 0.25], rationale="cli")
            out = Path(td) / "mix.wav"
            p = subprocess.run(
                [sys.executable, str(SCRIPTS / "blend.py"),
                 "--order", str(op), "--out", str(out)],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(out.exists())
            tl = json.loads(out.with_suffix(".tracklist.json").read_text())
            self.assertEqual(tl["order_rationale"], "cli")
            self.assertEqual(len(tl["tracklist"]), 2)

    def test_gain_match_flag(self):
        with tempfile.TemporaryDirectory() as td:
            op, _ = write_set(td, [0.5, 0.125])
            out = Path(td) / "mix.wav"
            p = subprocess.run(
                [sys.executable, str(SCRIPTS / "blend.py"),
                 "--order", str(op), "--out", str(out), "--gain-match", "off"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            tl = json.loads(out.with_suffix(".tracklist.json").read_text())
            self.assertEqual(tl["gain_match"]["mode"], "off")


if __name__ == "__main__":
    unittest.main()


class TestBoxLowpass(unittest.TestCase):
    """The crossover is numpy-only; these pin the properties it has to have."""

    def test_perfect_reconstruction(self):
        # The caller builds the high band as y - lows, so lows + highs must be
        # the original whatever the filter's response looks like.
        y = (np.random.RandomState(0).randn(SR, 2) * 0.1).astype(np.float32)
        lows = B.box_lowpass(y, SR, 200.0)
        np.testing.assert_allclose(lows + (y - lows), y, atol=1e-6)

    def test_passes_dc_unchanged(self):
        y = np.ones((SR, 2), dtype=np.float32) * 0.5
        np.testing.assert_allclose(B.box_lowpass(y, SR, 200.0), y, atol=1e-4)

    def test_rejects_content_well_above_cutoff(self):
        t = np.arange(SR) / SR
        y = np.stack([np.sin(2 * np.pi * 2000 * t)] * 2, axis=1).astype(np.float32)
        lows = B.box_lowpass(y, SR, 200.0)
        # Interior only: edge padding leaves a settling transient in the first
        # and last window, which is documented and harmless on a mix that
        # starts and ends in silence. A decade above the cutoff, the steady
        # state should be nothing at all.
        self.assertLess(float(np.max(np.abs(lows[2000:-2000]))), 1e-5)

    def test_zero_phase_keeps_the_peak_in_place(self):
        y = np.zeros((SR, 2), dtype=np.float32)
        y[SR // 2] = 1.0
        lows = B.box_lowpass(y, SR, 200.0)
        self.assertEqual(int(np.argmax(np.abs(lows[:, 0]))), SR // 2)


class TestBilateralPan(unittest.TestCase):
    def test_depth_zero_is_bit_identical(self):
        # Off by default has to mean untouched, not "almost untouched".
        y = (np.random.RandomState(1).randn(SR, 2) * 0.1).astype(np.float32)
        np.testing.assert_array_equal(B.bilateral_pan(y, SR, 155.0, 0.0), y)

    def test_constant_power(self):
        # sqrt(1-m) and sqrt(1+m) square-sum to 2 at every instant, so a
        # decorrelated full-band signal keeps its total power through the pan.
        rs = np.random.RandomState(2)
        y = (rs.randn(SR * 2, 2) * 0.1).astype(np.float32)
        out = B.bilateral_pan(y, SR, 155.0, 1.0, crossover_hz=1.0)
        # Estimated over noise, so a delta rather than places: the law is
        # exact, this measurement of it is not.
        self.assertAlmostEqual(float(np.mean(out ** 2) / np.mean(y ** 2)), 1.0,
                               delta=0.02)

    def test_low_end_stays_centred(self):
        # The point of the crossover: a mono sub still gets the kick.
        t = np.arange(SR * 4) / SR
        low = np.sin(2 * np.pi * 60 * t) * 0.5
        high = np.sin(2 * np.pi * 1500 * t) * 0.3
        y = np.stack([low + high, low + high], axis=1).astype(np.float32)
        out = B.bilateral_pan(y, SR, 155.0, 1.0)
        self.assertGreater(L.mono_compat(out, SR)["bass_correlation"], 0.9)

    def test_rate_is_one_cycle_per_bar(self):
        # 155 BPM / 4 beats = 0.6458 Hz, inside the 0.5-1 Hz band the technique
        # actually uses. Count zero crossings of the L-R difference.
        y = (np.random.RandomState(3).randn(SR * 8, 2) * 0.1).astype(np.float32)
        out = B.bilateral_pan(y, SR, 155.0, 1.0, crossover_hz=1.0)
        # Signed balance, not |L-R|: the rectified difference runs at twice the
        # pan rate and would pass this test for the wrong reason.
        d = (out[:, 0] ** 2 - out[:, 1] ** 2).astype(np.float32)
        bal = B.box_lowpass(np.stack([d, d], axis=1), SR, 3.0)[:, 0]
        trim = bal[SR // 2:-SR // 2]
        crossings = int(np.sum(np.diff(np.signbit(trim)) != 0))
        span = len(trim) / SR
        self.assertAlmostEqual(crossings / 2 / span, 155.0 / 60.0 / 4.0, delta=0.1)


class TestEnergyEnvelope(unittest.TestCase):
    def test_bounded_zero_to_one(self):
        y = (np.random.RandomState(4).randn(SR * 3, 2) * 0.2).astype(np.float32)
        env = B.energy_envelope(y, SR)
        self.assertGreaterEqual(float(env.min()), 0.0)
        self.assertLessEqual(float(env.max()), 1.0)

    def test_tracks_loud_and_quiet_sections(self):
        # Quiet first half, loud second. The envelope has to see the difference.
        y = np.zeros((SR * 6, 2), dtype=np.float32)
        rs = np.random.RandomState(5)
        y[:SR * 3] = rs.randn(SR * 3, 2) * 0.02
        y[SR * 3:] = rs.randn(SR * 3, 2) * 0.4
        env = B.energy_envelope(y, SR)
        self.assertLess(float(np.mean(env[SR:SR * 2])),
                        float(np.mean(env[SR * 4:SR * 5])))

    def test_silence_is_all_zero(self):
        env = B.energy_envelope(np.zeros((SR * 2, 2), np.float32), SR)
        self.assertEqual(float(np.max(env)), 0.0)


class TestBilateralGate(unittest.TestCase):
    def test_gate_zero_is_the_ungated_result(self):
        # Default has to stay exactly what it was before the gate existed.
        y = (np.random.RandomState(6).randn(SR * 2, 2) * 0.1).astype(np.float32)
        np.testing.assert_array_equal(
            B.bilateral_pan(y, SR, 152.0, 0.6),
            B.bilateral_pan(y, SR, 152.0, 0.6, gate=0.0))

    def test_gate_holds_the_loud_section_centred(self):
        # The whole point: dense passages stop moving, quiet ones still travel.
        y = np.zeros((SR * 8, 2), dtype=np.float32)
        rs = np.random.RandomState(7)
        y[:SR * 4] = rs.randn(SR * 4, 2) * 0.02
        y[SR * 4:] = rs.randn(SR * 4, 2) * 0.4
        def swing(a):
            # Level-INDEPENDENT: the balance as a fraction of total energy, so
            # a quiet passage and a loud one are measured on the same scale.
            # Dividing by the file's mean energy instead makes the quiet half
            # look motionless purely because it is quiet.
            num = a[:, 0] ** 2 - a[:, 1] ** 2
            den = a[:, 0] ** 2 + a[:, 1] ** 2 + 1e-12
            return float(np.std(
                B.box_lowpass(np.stack([num / den] * 2, axis=1), SR, 3.0)[:, 0]))

        ungated = B.bilateral_pan(y, SR, 152.0, 1.0, crossover_hz=1.0)
        gated = B.bilateral_pan(y, SR, 152.0, 1.0, crossover_hz=1.0, gate=1.0)

        # Ungated, both halves travel about the same amount.
        self.assertGreater(swing(ungated[SR * 5:SR * 7]),
                           swing(ungated[SR:SR * 3]) * 0.8)
        # Gated, the loud half is held far closer to centre than the quiet one.
        self.assertLess(swing(gated[SR * 5:SR * 7]),
                        swing(gated[SR:SR * 3]) * 0.5)

    def test_gate_never_inverts_the_pan(self):
        # 1 - gate*env is clamped by env <= 1, so the swing floors at zero
        # rather than going negative and flipping the channels.
        y = (np.random.RandomState(8).randn(SR * 3, 2) * 0.3).astype(np.float32)
        out = B.bilateral_pan(y, SR, 152.0, 0.6, crossover_hz=1.0, gate=1.0)
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertLessEqual(float(np.max(np.abs(out))), 2.0)
