"""master.py -- gain solving, ceiling, convergence, profiles, EQ, reporting."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from _ctx import (L, M, SCRIPTS, SR, noise, run_master, short_term_crest,
                  sine, spiky)


class TestGainSolving(unittest.TestCase):
    def test_already_on_target_is_a_noop(self):
        _, r = run_master(sine(), target_lufs=-9.0)
        self.assertAlmostEqual(r["gain"]["applied_db"], 0.0, delta=0.15)
        self.assertFalse(r["limiter"]["engaged"])

    def test_quiet_source_is_gained_up(self):
        _, r = run_master(sine(0.1), target_lufs=-9.0)
        self.assertAlmostEqual(r["gain"]["applied_db"], 11.0, delta=0.2)
        self.assertAlmostEqual(r["output_measured"]["lufs_i"], -9.0, delta=0.2)

    def test_loud_source_is_gained_down(self):
        _, r = run_master(sine(0.9), target_lufs=-9.0)
        self.assertAlmostEqual(r["gain"]["applied_db"], -8.1, delta=0.2)

    def test_gain_only_path_does_not_engage_the_limiter(self):
        # Headroom is available, so nothing should be limited.
        _, r = run_master(sine(0.1), target_lufs=-20.0)
        self.assertFalse(r["limiter"]["engaged"])

    def test_target_is_reached_without_limiting(self):
        for tgt in (-20.0, -14.0, -12.0):
            with self.subTest(target=tgt):
                _, r = run_master(sine(0.05), target_lufs=tgt)
                self.assertAlmostEqual(r["output_measured"]["lufs_i"], tgt,
                                       delta=0.2)


class TestCeiling(unittest.TestCase):
    def test_limiter_engages_when_threatened(self):
        _, r = run_master(spiky(), target_lufs=-9.0, ceiling_dbfs=-1.0)
        self.assertTrue(r["limiter"]["engaged"])

    def test_true_peak_ceiling_is_respected(self):
        for ceil in (-1.0, -2.0, -0.5):
            with self.subTest(ceiling=ceil):
                _, r = run_master(spiky(), target_lufs=-9.0, ceiling_dbfs=ceil)
                self.assertLessEqual(r["output_measured"]["true_peak_dbfs"],
                                     ceil + 0.05)

    def test_inter_sample_overshoot_triggers_a_corrective_pass(self):
        # alimiter holds a SAMPLE ceiling; the oversampled true peak overshoots
        # and has to be corrected by re-limiting lower.
        _, r = run_master(spiky(), target_lufs=-9.0, ceiling_dbfs=-1.0)
        self.assertIsNotNone(r["limiter"].get("corrective_pass_db"))
        self.assertLess(r["limiter"]["corrective_pass_db"], 0.0)

    def test_corrective_passes_are_bounded(self):
        # Must not loop: a pathological input reports failure instead.
        _, r = run_master(spiky(), target_lufs=-3.0, ceiling_dbfs=-1.0)
        self.assertIsInstance(r["limiter"], dict)

    def test_reduce_mode_holds_the_ceiling_without_limiting(self):
        _, r = run_master(spiky(), target_lufs=-9.0, ceiling_dbfs=-1.0,
                          limit_mode="reduce")
        self.assertFalse(r["limiter"]["engaged"])
        self.assertLessEqual(r["output_measured"]["true_peak_dbfs"], -1.0 + 0.05)
        self.assertIsNotNone(r["gain"]["loudness_given_up_db"])

    def test_reduce_mode_warns_that_it_gave_up_loudness(self):
        _, r = run_master(spiky(), target_lufs=-9.0, limit_mode="reduce")
        self.assertTrue(any("reduce" in w for w in r["warnings"]))


class TestConvergence(unittest.TestCase):
    """Limiting removes energy, so a single feed-forward gain undershoots."""

    def test_lands_on_target_with_the_limiter_engaged(self):
        _, r = run_master(noise(0.03), target_lufs=-12.0, ceiling_dbfs=-4.0,
                          max_limiting_pct=100.0)
        self.assertTrue(r["limiter"]["engaged"])
        self.assertAlmostEqual(r["output_measured"]["lufs_i"], -12.0, delta=0.2)

    def test_unreachable_target_stops_and_says_so(self):
        # A ceiling this low means limiting absorbs gain faster than the solver
        # can add it. It must stop at the pass limit and report the shortfall,
        # not spin.
        _, r = run_master(noise(0.03), target_lufs=-12.0, ceiling_dbfs=-5.5,
                          max_limiting_pct=100.0)
        self.assertEqual(r["gain"]["convergence_passes"], M.MAX_LOUDNESS_PASSES)
        self.assertTrue(any("landed" in w or "stopped" in w
                            for w in r["warnings"]))

    def test_convergence_pass_count_is_reported(self):
        _, r = run_master(noise(0.03), target_lufs=-12.0, ceiling_dbfs=-4.0,
                          max_limiting_pct=100.0)
        self.assertGreaterEqual(r["gain"]["convergence_passes"], 1)
        self.assertLessEqual(r["gain"]["convergence_passes"],
                             M.MAX_LOUDNESS_PASSES)

    def test_cost_cap_stops_the_chase(self):
        _, r = run_master(noise(0.03), target_lufs=-12.0, ceiling_dbfs=-6.0,
                          max_limiting_pct=5.0)
        self.assertTrue(any("stopped" in w for w in r["warnings"]))

    def test_cost_cap_keeps_the_cheaper_result(self):
        capped = run_master(noise(0.03), target_lufs=-12.0, ceiling_dbfs=-6.0,
                            max_limiting_pct=5.0)[1]
        free = run_master(noise(0.03), target_lufs=-12.0, ceiling_dbfs=-6.0,
                          max_limiting_pct=100.0)[1]
        self.assertLessEqual(capped["limiter"]["limited_pct"],
                             free["limiter"]["limited_pct"] + 0.1)

    def test_shortfall_warning_is_not_duplicated(self):
        _, r = run_master(noise(0.03), target_lufs=-12.0, ceiling_dbfs=-6.0,
                          max_limiting_pct=5.0)
        self.assertLessEqual(sum("short" in w or "landed" in w
                                 for w in r["warnings"]), 1)


class TestIdempotence(unittest.TestCase):
    def test_mastering_the_master_is_a_noop(self):
        out, _ = run_master(sine(0.1), target_lufs=-9.0)
        _, r2 = run_master(out, target_lufs=-9.0)
        self.assertAlmostEqual(r2["gain"]["applied_db"], 0.0, delta=0.2)
        self.assertFalse(r2["limiter"]["engaged"])

    def test_repeated_mastering_does_not_drift(self):
        buf = sine(0.1)
        for _ in range(3):
            buf, r = run_master(buf, target_lufs=-9.0)
        self.assertAlmostEqual(r["output_measured"]["lufs_i"], -9.0, delta=0.25)


class TestTransientCost(unittest.TestCase):
    """The reason the default target is -11.5 rather than a chart figure."""

    def test_no_limiting_preserves_crest(self):
        y = noise(0.05)
        out, r = run_master(y, target_lufs=L.measure(y)["lufs_i"])
        self.assertFalse(r["limiter"]["engaged"])
        self.assertAlmostEqual(short_term_crest(out), short_term_crest(y),
                               delta=0.15)

    def test_hard_limiting_costs_crest(self):
        y = noise(0.03)
        out, r = run_master(y, target_lufs=-12.0, ceiling_dbfs=-6.0,
                            max_limiting_pct=100.0)
        self.assertTrue(r["limiter"]["engaged"])
        self.assertLess(short_term_crest(out), short_term_crest(y) - 0.5)

    def test_louder_target_costs_more_crest(self):
        # The measured trade-off behind the -11.5 default: loudness is bought
        # with transients, every time.
        y = noise(0.03)
        soft, rs = run_master(y, target_lufs=-16.0)
        hard, rh = run_master(y, target_lufs=-12.0, ceiling_dbfs=-4.5,
                              max_limiting_pct=100.0)
        self.assertFalse(rs["limiter"]["engaged"])
        self.assertTrue(rh["limiter"]["engaged"])
        self.assertLess(short_term_crest(hard), short_term_crest(soft) - 0.5)


class TestProfiles(unittest.TestCase):
    def test_default_profile_is_device(self):
        self.assertEqual(M.load_profiles()["default"], "device")

    def test_device_profile_does_not_limit_this_material(self):
        prof, _ = M.resolve_profile("device")
        self.assertAlmostEqual(prof["lufs"], -11.5)
        self.assertAlmostEqual(prof["tp"], -1.0)

    def test_club_is_louder_than_device(self):
        club, _ = M.resolve_profile("club")
        device, _ = M.resolve_profile("device")
        self.assertGreater(club["lufs"], device["lufs"])

    def test_every_profile_has_a_stated_rationale(self):
        # A profile whose numbers nobody can justify is a magic number.
        for name, prof in M.load_profiles()["profiles"].items():
            with self.subTest(profile=name):
                self.assertTrue(prof.get("summary"))
                self.assertTrue(prof.get("rationale"))
                for key in ("lufs", "tp", "max_limiting_pct"):
                    self.assertIn(key, prof)

    def test_profiles_carry_no_eq(self):
        # Tonal moves stay explicit; a profile that silently reshapes the
        # spectrum is one nobody can reason about.
        for name, prof in M.load_profiles()["profiles"].items():
            with self.subTest(profile=name):
                self.assertNotIn("low_shelf_db", prof)
                self.assertNotIn("high_shelf_db", prof)
                self.assertNotIn("eq", prof)

    def test_unknown_profile_fails_loudly(self):
        with self.assertRaises(SystemExit):
            M.resolve_profile("stadium")

    def test_ceilings_are_safe(self):
        for name, prof in M.load_profiles()["profiles"].items():
            with self.subTest(profile=name):
                self.assertLessEqual(prof["tp"], -0.5)

    def test_describe_lists_every_profile(self):
        text = M.describe_profiles()
        for name in M.load_profiles()["profiles"]:
            self.assertIn(name, text)


class TestTiltAndShelves(unittest.TestCase):
    def test_tilt_falls_with_frequency(self):
        prof = M.tilt_profile(-1.5)
        self.assertGreater(prof["sub"], prof["mid"])
        self.assertGreater(prof["mid"], prof["air"])

    def test_tilt_is_mean_normalised(self):
        self.assertAlmostEqual(float(np.mean(list(M.tilt_profile(-1.5).values()))),
                               0.0, delta=0.05)

    def test_flat_tilt_is_flat(self):
        vals = list(M.tilt_profile(0.0).values())
        self.assertAlmostEqual(max(vals) - min(vals), 0.0, delta=0.01)

    def test_reference_file_loads_and_records_provenance(self):
        _, spec = M.load_tilt_reference()
        self.assertIn("provenance", spec)
        self.assertTrue(spec["provenance"].get("sources"))
        self.assertTrue(spec.get("limits"))

    def test_manual_shelves_are_clamped(self):
        lo, hi, _ = M.resolve_shelves(sine(), None, "shelf", 9.0, -9.0, 1.5)
        self.assertAlmostEqual(lo, 1.5)
        self.assertAlmostEqual(hi, -1.5)

    def test_curve_mode_is_gentle_on_real_material(self):
        # If it wants the full clamp on both ends, suspect the curve.
        lo, hi, detail = M.resolve_shelves(noise(), None, "curve", 0.0, 0.0, 1.5)
        self.assertEqual(detail["source"], "curve")
        self.assertIn("profile_delta_db", detail)

    def test_match_mode_against_itself_wants_nothing(self):
        y = noise()
        lo, hi, _ = M.resolve_shelves(y, y, "match", 0.0, 0.0, 1.5)
        self.assertAlmostEqual(lo, 0.0, delta=0.05)
        self.assertAlmostEqual(hi, 0.0, delta=0.05)

    def test_match_is_level_independent(self):
        # A louder reference must not read as wanting a broadband boost.
        y = noise()
        lo, hi, _ = M.resolve_shelves(y, L.apply_gain(y, 9.0), "match", 0, 0, 1.5)
        self.assertAlmostEqual(lo, 0.0, delta=0.05)
        self.assertAlmostEqual(hi, 0.0, delta=0.05)

    def test_eq_none_leaves_bands_untouched(self):
        _, r = run_master(noise(), eq_mode="none")
        self.assertIsNone(r["eq"]["bands_after"])


class TestReport(unittest.TestCase):
    def test_report_is_json_serialisable(self):
        # numpy scalars leak easily out of a report built from measurements.
        _, r = run_master(spiky(), target_lufs=-9.0)
        json.dumps(r, default=M._jsonable)

    def test_report_has_the_headline_numbers(self):
        _, r = run_master(spiky(), target_lufs=-9.0, do_mono=True)
        for key in ("target", "eq", "input_measured", "gain", "limiter",
                    "output_measured", "mono", "deltas", "warnings", "tool"):
            self.assertIn(key, r)

    def test_tool_string_records_the_loudnorm_decision(self):
        _, r = run_master(sine())
        self.assertIn("loudnorm not used", r["tool"])

    def test_deltas_are_consistent_with_measurements(self):
        _, r = run_master(sine(0.1), target_lufs=-9.0)
        want = r["output_measured"]["lufs_i"] - r["input_measured"]["lufs_i"]
        self.assertAlmostEqual(r["deltas"]["lufs"], want, delta=0.05)


class TestCli(unittest.TestCase):
    """The CLI is the interface people actually use."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "master.py"), *args],
            capture_output=True, text=True)

    def test_list_profiles(self):
        p = self._run("--list-profiles")
        self.assertEqual(p.returncode, 0)
        self.assertIn("device", p.stdout)
        self.assertIn("club", p.stdout)

    def test_missing_input_is_an_error(self):
        self.assertNotEqual(self._run().returncode, 0)

    def test_eq_match_requires_a_reference(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.wav"
            sf.write(str(src), sine(), SR, subtype="PCM_24")
            p = self._run("--in", str(src), "--dry-run", "--eq", "match")
            self.assertNotEqual(p.returncode, 0)

    def test_dry_run_writes_no_audio(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.wav", Path(td) / "out.wav"
            sf.write(str(src), sine(), SR, subtype="PCM_24")
            p = self._run("--in", str(src), "--out", str(dst), "--dry-run")
            self.assertEqual(p.returncode, 0)
            self.assertFalse(dst.exists())

    def test_writes_24_bit_at_source_rate(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.wav", Path(td) / "out.wav"
            sf.write(str(src), sine(), SR, subtype="PCM_24")
            p = self._run("--in", str(src), "--out", str(dst))
            self.assertEqual(p.returncode, 0, p.stderr)
            info = sf.info(str(dst))
            self.assertEqual(info.samplerate, SR)   # loudnorm would give 192k
            self.assertIn("24", info.subtype)

    def test_explicit_lufs_overrides_the_profile(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.wav"
            sf.write(str(src), sine(0.1), SR, subtype="PCM_24")
            p = self._run("--in", str(src), "--dry-run",
                          "--profile", "club", "--lufs", "-14")
            rep = json.loads(p.stdout)
            self.assertEqual(rep["target"]["lufs_i"], -14.0)
            self.assertEqual(rep["profile"]["name"], "club")
            self.assertIn("--lufs", rep["profile"]["overridden"])

    def test_profile_sets_the_target(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.wav"
            sf.write(str(src), sine(0.1), SR, subtype="PCM_24")
            rep = json.loads(self._run("--in", str(src), "--dry-run",
                                       "--profile", "club").stdout)
            self.assertEqual(rep["target"]["lufs_i"], -9.0)
            self.assertIsNone(rep["profile"]["overridden"])

    def test_unknown_profile_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.wav"
            sf.write(str(src), sine(), SR, subtype="PCM_24")
            p = self._run("--in", str(src), "--dry-run", "--profile", "stadium")
            self.assertNotEqual(p.returncode, 0)

    def test_rejects_wrong_sample_rate(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.wav"
            sf.write(str(src), sine(sr=48000), 48000, subtype="PCM_24")
            self.assertNotEqual(
                self._run("--in", str(src), "--dry-run").returncode, 0)

    def test_tracklist_is_preserved_not_rebuilt(self):
        # Load-and-mutate: an unknown key added by hand must survive.
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.wav", Path(td) / "out.wav"
            tl = Path(td) / "a.tracklist.json"
            sf.write(str(src), sine(), SR, subtype="PCM_24")
            tl.write_text(json.dumps(
                {"output": "a.wav", "order_rationale": "keep me",
                 "tracklist": []}), encoding="utf-8")
            p = self._run("--in", str(src), "--out", str(dst),
                          "--tracklist", str(tl))
            self.assertEqual(p.returncode, 0, p.stderr)
            got = json.loads(dst.with_suffix(".tracklist.json").read_text())
            self.assertEqual(got["order_rationale"], "keep me")
            self.assertIn("master", got)


if __name__ == "__main__":
    unittest.main()
