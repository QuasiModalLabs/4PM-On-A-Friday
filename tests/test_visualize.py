"""visualize.py -- variant resolution, hook effects, determinism.

The visual result is not testable here for the same reason the rest of the suite
is anchored on arithmetic: nobody in this loop can look at the video. What is
testable is that the right variant is chosen, that the motion is bounded and
reproducible, and that every variant renders a frame of the right shape.
"""

import unittest

import numpy as np

from _ctx import V, N_BARS


def features(n=64, kick=0.9):
    return {"n_frames": n,
            "kick": np.full(n, kick, np.float32),
            "rms": np.full(n, 0.5, np.float32),
            "bars": np.full((n, N_BARS), 0.4, np.float32)}


def fonts_for(size):
    return {"hook": V.load_font("bold", int(size * 0.072)),
            "body": V.load_font("regular", int(size * 0.022)),
            "label": V.load_font("mono", int(size * 0.018))}


SEG = {"position": 1, "title": "On The Floor",
       "hook": "Why are they on the floor.",
       "review": "Renovation is horrible nothing in stock anywhere."}


class TestVariantResolution(unittest.TestCase):
    def test_variant_key(self):
        for name in V.EFFECTS:
            self.assertEqual(V.variant_for({"variant": name}), name)

    def test_effect_key_overrides_variant(self):
        # The explicit override is the whole point of having two keys.
        self.assertEqual(
            V.variant_for({"effect": "uptempo", "variant": "melodic"}), "uptempo")

    def test_unknown_variant_falls_back(self):
        self.assertEqual(V.variant_for({"variant": "disco"}), V.DEFAULT_VARIANT)
        self.assertEqual(V.variant_for({}), V.DEFAULT_VARIANT)

    def test_case_and_whitespace_tolerated(self):
        self.assertEqual(V.variant_for({"variant": "  RAW  "}), "raw")

    def test_bpm_bands_match_step_2(self):
        # A text.json written before `variant` existed still varies per track,
        # because blend.py puts original_bpm in every tracklist entry.
        for bpm, want in [(150.0, "euphoric"), (152.0, "euphoric"),
                          (154.0, "melodic"), (157.0, "raw-melodic"),
                          (159.0, "raw"), (172.0, "uptempo")]:
            self.assertEqual(V.variant_for({"original_bpm": bpm}), want, bpm)

    def test_variant_key_beats_bpm(self):
        self.assertEqual(
            V.variant_for({"variant": "euphoric", "original_bpm": 172.0}),
            "euphoric")


class TestEffectParams(unittest.TestCase):
    def test_pixel_figures_scale_with_frame(self):
        a = V.effect_params({"variant": "uptempo"}, 1080)
        b = V.effect_params({"variant": "uptempo"}, 540)
        self.assertAlmostEqual(b["jitter"], a["jitter"] / 2, places=6)
        self.assertAlmostEqual(b["split"], a["split"] / 2, places=6)

    def test_does_not_mutate_the_table(self):
        before = dict(V.EFFECTS["uptempo"])
        V.effect_params({"variant": "uptempo"}, 540)
        self.assertEqual(V.EFFECTS["uptempo"], before)

    def test_restraint_is_enforced_by_the_table(self):
        for name, p in V.EFFECTS.items():
            self.assertLessEqual(p["jitter"], 3.0, name)
            self.assertLessEqual(p["split"], 4.0, name)
            self.assertLessEqual(p["pulse"], 0.06, name)


class TestJitter(unittest.TestCase):
    def test_deterministic(self):
        # A re-render must be identical, or the pre-flight stops describing the
        # render it is meant to check.
        self.assertEqual(V.frame_jitter(77, 3.0), V.frame_jitter(77, 3.0))

    def test_bounded(self):
        for i in range(2000):
            dx, dy = V.frame_jitter(i, 3.0)
            self.assertLessEqual(abs(dx), 3.0)
            self.assertLessEqual(abs(dy), 3.0)

    def test_zero_amount_is_still(self):
        self.assertEqual(V.frame_jitter(999, 0.0), (0.0, 0.0))

    def test_actually_moves_between_frames(self):
        vals = {V.frame_jitter(i, 3.0) for i in range(50)}
        self.assertGreater(len(vals), 40)


class TestHookLayer(unittest.TestCase):
    def test_cached_layer_is_the_same_object(self):
        f = V.load_font("bold", 40)
        a = V.hook_layer("Why are they on the floor.", f, 540, 400)
        b = V.hook_layer("Why are they on the floor.", f, 540, 400)
        self.assertIs(a, b)

    def test_layer_has_alpha_and_fits_the_width(self):
        f = V.load_font("bold", 40)
        layer = V.hook_layer("An hour just for milk.", f, 540, 400)
        self.assertEqual(layer.mode, "RGBA")
        self.assertLessEqual(layer.width, 400)
        self.assertGreater(np.asarray(layer)[:, :, 3].max(), 0)


class TestRenderFrame(unittest.TestCase):
    SIZE = 360

    def test_every_variant_renders(self):
        f, fo = features(), fonts_for(self.SIZE)
        for name in list(V.EFFECTS) + ["nonsense"]:
            img = V.render_frame(f, 10, self.SIZE, {**SEG, "variant": name},
                                 fo, 3.0, 100.0)
            self.assertEqual(img.size, (self.SIZE, self.SIZE), name)
            self.assertEqual(img.mode, "RGB", name)

    def test_variants_differ_on_screen(self):
        f, fo = features(), fonts_for(self.SIZE)
        shot = lambda v: np.asarray(V.render_frame(  # noqa: E731
            f, 10, self.SIZE, {**SEG, "variant": v}, fo, 3.0, 100.0))
        self.assertFalse(np.array_equal(shot("euphoric"), shot("raw")))
        self.assertFalse(np.array_equal(shot("melodic"), shot("uptempo")))

    def test_unknown_variant_renders_as_the_default(self):
        f, fo = features(), fonts_for(self.SIZE)
        shot = lambda v: np.asarray(V.render_frame(  # noqa: E731
            f, 10, self.SIZE, {**SEG, "variant": v}, fo, 3.0, 100.0))
        np.testing.assert_array_equal(shot("disco"), shot(V.DEFAULT_VARIANT))

    def test_re_render_is_identical(self):
        f, fo = features(), fonts_for(self.SIZE)
        shot = lambda: np.asarray(V.render_frame(  # noqa: E731
            f, 10, self.SIZE, {**SEG, "variant": "uptempo"}, fo, 3.0, 100.0))
        np.testing.assert_array_equal(shot(), shot())

    def test_silence_stills_every_variant(self):
        # Jitter is weighted by kick, so nothing should twitch through a
        # breakdown. This was a real bug: flat jitter shimmered in silence,
        # which reads as a broken font rather than a reaction to the audio.
        quiet, fo = features(kick=0.0), fonts_for(self.SIZE)
        for name in V.EFFECTS:
            a = np.asarray(V.render_frame(quiet, 10, self.SIZE,
                                          {**SEG, "variant": name}, fo, 3.0, 100.0))
            b = np.asarray(V.render_frame(quiet, 11, self.SIZE,
                                          {**SEG, "variant": name}, fo, 3.1, 100.0))
            np.testing.assert_array_equal(a, b, err_msg=name)

    def test_motion_ranks_by_variant_on_a_kick(self):
        # The ordering is the whole point: calm variants move less than angry
        # ones. Bars are zeroed so this measures the hook and nothing else.
        loud = features(kick=1.0)
        loud["bars"] = np.zeros_like(loud["bars"])
        fo = fonts_for(self.SIZE)

        def motion(name):
            fr = [np.asarray(V.render_frame(loud, i, self.SIZE,
                                            {**SEG, "variant": name}, fo,
                                            i / 30, 100.0)).astype(np.int16)
                  for i in (20, 21)]
            return float(np.mean(np.abs(fr[1] - fr[0])))

        self.assertLess(motion("melodic"), motion("raw"))
        self.assertLess(motion("euphoric"), motion("raw"))
        self.assertLess(motion("raw-melodic"), motion("uptempo"))

    def test_missing_hook_falls_back_to_title(self):
        f, fo = features(), fonts_for(self.SIZE)
        img = V.render_frame(f, 10, self.SIZE, {"position": 1, "title": "T"},
                             fo, 3.0, 100.0)
        self.assertEqual(img.size, (self.SIZE, self.SIZE))


class TestPulseEnvelope(unittest.TestCase):
    """The scale swell. Both faults it had were measurable, so both are pinned."""

    def test_pulse_feature_exists_and_is_bounded(self):
        y = np.zeros(44100 * 3, np.float32)
        t = np.arange(int(44100 * 0.08)) / 44100
        for h in (0.5, 1.0, 1.5, 2.0, 2.5):
            s = int(h * 44100)
            y[s:s + len(t)] += np.sin(2 * np.pi * 60 * t) * np.exp(-t * 40)
        f = V.compute_features(y, 44100, 30)
        self.assertIn("pulse", f)
        self.assertEqual(len(f["pulse"]), f["n_frames"])
        self.assertGreaterEqual(float(f["pulse"].min()), 0.0)

    def test_pulse_is_smoother_than_raw_kick(self):
        rs = np.random.RandomState(11)
        y = (rs.randn(44100 * 4) * 0.1).astype(np.float32)
        f = V.compute_features(y, 44100, 30)
        self.assertLess(float(np.std(np.diff(f["pulse"]))),
                        float(np.std(np.diff(f["kick"]))))

    def test_pulse_still_lands_on_the_transient(self):
        # The follower must not fix chatter by making everything late.
        y = np.zeros(44100 * 3, np.float32)
        t = np.arange(int(44100 * 0.08)) / 44100
        hit = int(1.5 * 44100)
        y[hit:hit + len(t)] += np.sin(2 * np.pi * 60 * t) * np.exp(-t * 40)
        f = V.compute_features(y, 44100, 30)
        peak = int(np.argmax(f["pulse"]))
        self.assertLessEqual(abs(peak / 30 - 1.5), 0.05)   # within 50 ms

    def test_scale_quantisation_resolves_the_whole_pulse(self):
        # The original bug: 1/16 steps of ABSOLUTE scale is coarser than the
        # entire pulse range, so every variant collapsed to one or two sizes
        # and the swell became a comparator. That produced both the popping
        # and the apparent loss of sync.
        for name, p in V.EFFECTS.items():
            if p["pulse"] <= 0:
                continue
            sizes = {round(1.0 + round(k * V.SCALE_STEPS) / V.SCALE_STEPS
                           * p["pulse"], 6)
                     for k in np.linspace(0, 1.4, 200)}
            self.assertGreater(len(sizes), 12, name)
