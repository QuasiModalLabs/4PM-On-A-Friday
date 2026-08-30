#!/usr/bin/env python3
"""Master a finished mix: loudness to target, true-peak ceiling, optional shelves.

    python master.py --in mix.wav --out mastered.wav
    python master.py --in mix.wav --dry-run          # measure only, writes nothing
    python master.py --selftest                      # arithmetic, no real audio

A separate stage from blend.py on purpose: blending is the expensive part
(stretching every track), and you must be able to re-master at a different
target without re-blending.

Order of operations is EQ -> measure -> gain -> limit -> re-measure. EQ comes
first because it changes loudness; everything after is measured on the signal
that actually exists rather than on a prediction.

Every stage reports numbers, because nobody running this can hear the result
from a JSON file. What the numbers do NOT tell you is whether the master sounds
good -- in particular whether the limiter is pumping. Check `limited_pct` and
`gr_max_db`, then listen.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loudness as L  # noqa: E402

SR = L.SR

# Where the blend already sits, so the limiter never engages and the master is a
# pure safety pass: level match, peak ceiling, mono check, no transient cost.
#
# This is deliberately NOT the commercial hardstyle figure of -7 to -5 LUFS.
# Suno sources arrive around -14 LUFS with -4 dBTP -- already dynamic, with
# headroom, and needing no rescue. Measured on a real set, every dB above the
# blend's own level is paid for in transients: a source track pushed to -11.5
# needs 0% limiting, to -9.2 needs 19.9%, to -8.9 needs 33.8%; the assembled mix
# at -9.1 needs 46.5%, because crossfades sum two tracks and raise density
# further. Short-term crest went 9.20 dB at the blend to 8.25 at -9 and 7.83 at
# -8 -- and on hardstyle, crest is the kick.
#
# Chase a chart-loudness number only with ears on the result: --lufs -9 for a
# louder set, -6 for club-loud, expecting real limiting at both.
DEFAULT_LUFS = -11.5

# -1.0 dBTP, not -0.1. The shipped artifact is an MP4 and visualize.py encodes
# AAC at 256k; lossy encoding generates inter-sample peaks above the PCM peak.
# -1.0 survives that encode.
DEFAULT_TP = -1.0

EQ_LIMIT = 1.5   # max shelf move, dB. Broad and gentle enough to be recoverable.

# alimiter holds a sample-peak ceiling; the true-peak overshoot is corrected by
# re-limiting to a lower working ceiling. Bounded so a pathological input
# reports failure instead of spinning.
MAX_CORRECTIVE_PASSES = 3

# Limiting removes energy, so the gain must be re-solved against the measured
# output to actually land on target. Bounded for the same reason.
MAX_LOUDNESS_PASSES = 4
LOUDNESS_TOLERANCE_LU = 0.15

# Past this much of the file being limited, chasing the target costs more in
# dynamics than the extra loudness is worth. Overridable; not a hard refusal.
MAX_LIMITING_PCT = 60.0



def _jsonable(o):
    """numpy scalars are not JSON-serialisable; a report built from
    measurements will always sprout a few."""
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError("not JSON serialisable: %r" % (type(o),))


TILT_JSON = Path(__file__).resolve().parent.parent / "references" / "tilt.json"
PROFILES_JSON = Path(__file__).resolve().parent.parent / "references" / "profiles.json"


def load_profiles(path=PROFILES_JSON):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_profile(name, path=PROFILES_JSON):
    """Named delivery profile -> loudness settings.

    Profiles carry loudness only, never EQ: a profile that quietly reshapes the
    spectrum is one nobody can reason about.
    """
    spec = load_profiles(path)
    profs = spec["profiles"]
    if name not in profs:
        raise SystemExit("unknown profile %r; available: %s"
                         % (name, ", ".join(sorted(profs))))
    return profs[name], spec


def describe_profiles(path=PROFILES_JSON):
    spec = load_profiles(path)
    lines = ["Delivery profiles (references/profiles.json):", ""]
    for name, prof in spec["profiles"].items():
        default = "  [default]" if name == spec.get("default") else ""
        lines.append("  %-9s %6.1f LUFS / %.1f dBTP%s" %
                     (name, prof["lufs"], prof["tp"], default))
        lines.append("            %s" % prof["summary"])
        for r in prof.get("rationale", []):
            lines.append("            %s" % r)
        lines.append("")
    lines.append("  " + spec.get("how_to_judge", ""))
    return chr(10).join(lines)


def tilt_profile(tilt_db_per_oct, ref_hz=1000.0, **_):
    """The tilt as a mean-normalised per-octave profile, comparable to
    loudness.band_profile().

    Computed rather than tabulated: the whole reference is one documented number
    (see references/tilt.json) instead of six figures nobody can source.

    Evaluated at each band's geometric centre. A tilt is a straight line on a
    log-frequency axis, so the centre frequency is the honest single value for
    the band -- and it must be compared per octave, which is what
    band_profile() returns.
    """
    centers = L.band_centers()
    vals = {name: tilt_db_per_oct * np.log2(c / ref_hz)
            for name, (c, _span) in centers.items()}
    mean = float(np.mean(list(vals.values())))
    return {k: round(v - mean, 2) for k, v in vals.items()}


def load_tilt_reference(path=TILT_JSON):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    prof = tilt_profile(float(spec["tilt_db_per_octave"]),
                        float(spec.get("reference_hz", 1000.0)))
    return prof, spec


def resolve_shelves(buf, reference, mode, low_db, high_db, eq_limit,
                    tilt_path=TILT_JSON):
    """Return (low_db, high_db, detail). Clamped to +/- eq_limit."""
    if mode == "shelf":
        lo = float(np.clip(low_db, -eq_limit, eq_limit))
        hi = float(np.clip(high_db, -eq_limit, eq_limit))
        return lo, hi, {"source": "manual"}

    # Both remaining modes compare RELATIVE band profiles. Absolute comparison
    # would turn a level difference into a broadband boost that the gain stage
    # then removes -- EQ'ing nothing while reporting that it did.
    mine = L.band_profile(buf)
    if mode == "curve":
        ref, spec = load_tilt_reference(tilt_path)
        source = {"source": "curve",
                  "curve": spec.get("name"),
                  "tilt_db_per_octave": spec.get("tilt_db_per_octave")}
    else:
        ref = L.band_profile(reference)
        source = {"source": "reference"}
    source["profile_delta_db"] = {k: round(ref[k] - mine[k], 2) for k in mine}
    low_delta = np.mean([ref[b] - mine[b] for b in ("sub", "low")])
    high_delta = ref["air"] - mine["air"]
    lo = float(np.clip(low_delta, -eq_limit, eq_limit))
    hi = float(np.clip(high_delta, -eq_limit, eq_limit))
    return lo, hi, {
        **source,
        "low_wanted_db": round(float(low_delta), 2),
        "high_wanted_db": round(float(high_delta), 2),
        "low_clamped": bool(abs(low_delta) > eq_limit),
        "high_clamped": bool(abs(high_delta) > eq_limit),
    }


def master(buf, *, target_lufs, ceiling_dbfs, limit_mode, eq_mode,
           low_shelf_db, high_shelf_db, eq_limit, reference, do_mono=True,
           max_limiting_pct=MAX_LIMITING_PCT):
    rep = {"target": {"lufs_i": target_lufs, "true_peak_dbfs": ceiling_dbfs,
                      "limit_mode": limit_mode}}
    warnings = []

    # --- 1. EQ (opt-in) ---------------------------------------------------
    eq = {"mode": eq_mode, "low_shelf_db": 0.0, "high_shelf_db": 0.0}
    eq["bands_before"] = L.band_energy_db(buf)
    if eq_mode != "none":
        lo, hi, detail = resolve_shelves(
            buf, reference, eq_mode, low_shelf_db, high_shelf_db, eq_limit)
        eq["reference_profile"] = detail.pop("_profile", None)
        buf = L.apply_shelves(buf, lo, hi)
        eq.update({"low_shelf_db": round(lo, 2), "high_shelf_db": round(hi, 2),
                   "limit_db": eq_limit, **detail})
        eq["bands_after"] = L.band_energy_db(buf)
        if detail.get("low_clamped") or detail.get("high_clamped"):
            warnings.append(
                "EQ match wanted more than +/-%.1f dB and was clamped; suspect the "
                "reference before trusting the result" % eq_limit)
    else:
        eq["bands_after"] = None
    rep["eq"] = eq

    # --- 2. measure -------------------------------------------------------
    m_in = L.measure(buf)
    rep["input_measured"] = m_in
    if m_in.get("short"):
        warnings.append(
            "input is %.1fs; ebur128's integrated gate is unreliable below %.0fs"
            % (m_in["duration_s"], L.MIN_RELIABLE_S))

    # --- 3. gain (a scalar, exact, reportable) ----------------------------
    gain_db = target_lufs - m_in["lufs_i"]
    predicted_tp = m_in["true_peak_dbfs"] + gain_db
    reduced = None
    if limit_mode == "reduce" and predicted_tp > ceiling_dbfs:
        reduced = predicted_tp - ceiling_dbfs
        gain_db -= reduced
        warnings.append(
            "--limit-mode reduce: gave up %.2f dB of loudness to hold the ceiling; "
            "output will be below target" % reduced)
    # --- 4/5/6. limit to the ceiling, then converge on the loudness target --
    #
    # Limiting removes energy, so a single feed-forward gain lands short of the
    # target -- measured 0.7 LU short at -8 LUFS on a real set. "Normalise to a
    # target" has to actually reach the target, so the gain is re-solved against
    # the MEASURED output and the limiter re-run. Bounded, and every extra dB of
    # limiting it costs is reported.
    def limit_to_ceiling(sig):
        """Limit, then correct the inter-sample overshoot alimiter leaves."""
        if limit_mode != "limit" or L.measure(sig)["true_peak_dbfs"] <= ceiling_dbfs:
            return sig, {"engaged": False}, L.measure(sig)
        o, li = L.apply_limiter(sig, ceiling_dbfs)
        mo = L.measure(o)
        # alimiter enforces a SAMPLE-peak ceiling. The 4x-oversampled true peak
        # still overshoots -- measured ~0.6 dB on music, ~1.1 dB on square-edged
        # transients. Lowering the working ceiling by the measured overshoot
        # converges, but not always in one step, because limiting harder changes
        # the waveform. Iterate, strictly bounded.
        trim = 0.0
        for _ in range(MAX_CORRECTIVE_PASSES):
            if mo["true_peak_dbfs"] <= ceiling_dbfs + 0.02:
                break
            trim += (mo["true_peak_dbfs"] - ceiling_dbfs) + 0.05
            o, li = L.apply_limiter(sig, ceiling_dbfs - trim)
            li["corrective_pass_db"] = round(-trim, 2)
            mo = L.measure(o)
        return o, li, mo

    # Converging on the target is bounded by what it COSTS, not just by a pass
    # count. On a dense set the last half-decibel is bought with a lot of
    # limiting -- measured here: +0.5 LU cost 18 more points of limited_pct and
    # 0.6 LU of loudness range. Past max_limiting_pct, stop and keep the last
    # cheaper result rather than grinding the dynamics away to hit a number.
    passes = 0
    best = None
    stopped_on_cost = None
    for _ in range(MAX_LOUDNESS_PASSES):
        passes += 1
        pre_limit = L.apply_gain(buf, gain_db)
        out, lim, m_out = limit_to_ceiling(pre_limit)
        if best is not None and lim.get("limited_pct", 0.0) > max_limiting_pct:
            stopped_on_cost = lim.get("limited_pct", 0.0)
            out, lim, m_out, gain_db = best
            passes -= 1
            break
        best = (out, lim, m_out, gain_db)
        residual = target_lufs - m_out["lufs_i"]
        # In reduce mode the shortfall is deliberate -- do not chase it.
        if limit_mode == "reduce" or abs(residual) <= LOUDNESS_TOLERANCE_LU:
            break
        gain_db += residual

    if stopped_on_cost is not None:
        warnings.append(
            "stopped %.1f LU short of the %.1f LUFS target: reaching it needed "
            "limiting on %.1f%% of the file (cap %.0f%%). Raise --max-limiting-pct "
            "to insist, or accept the quieter, less-squashed master"
            % (target_lufs - m_out["lufs_i"], target_lufs,
               stopped_on_cost, max_limiting_pct))

    rep["gain"] = {
        "applied_db": round(gain_db, 2),
        "predicted_true_peak_dbfs": round(predicted_tp, 2),
        "loudness_given_up_db": round(reduced, 2) if reduced else None,
        "convergence_passes": passes,
    }
    rep["limiter"] = lim
    rep["output_measured"] = m_out

    # Only worth saying when the cost cap did not already explain the shortfall.
    if (stopped_on_cost is None and limit_mode != "reduce"
            and abs(target_lufs - m_out["lufs_i"]) > LOUDNESS_TOLERANCE_LU):
        warnings.append(
            "landed at %.1f LUFS against a %.1f target after %d pass%s; the "
            "limiter is absorbing the difference"
            % (m_out["lufs_i"], target_lufs, passes, "" if passes == 1 else "es"))

    if m_out["true_peak_dbfs"] > ceiling_dbfs + 0.05:
        warnings.append(
            "true peak %.2f dBFS still exceeds the %.2f dBFS ceiling -- this is a "
            "bug in the tool, not a property of the music"
            % (m_out["true_peak_dbfs"], ceiling_dbfs))
    if lim.get("limited_pct", 0) > 25:
        # Not necessarily a fault -- the club profile buys density this way on
        # purpose. State the cost; do not imply the choice was wrong.
        warnings.append(
            "limiter touched %.1f%% of the file (worst %.2f dB). That is the "
            "transient cost of this target and where pumping would show; it is "
            "expected if you asked for a loud master. Listen before shipping, "
            "and level-match if you A/B it"
            % (lim["limited_pct"], lim["gr_max_db"]))

    # --- 7. mono compatibility on the finished master ---------------------
    if do_mono:
        mono = L.mono_compat(out)
        rep["mono"] = mono
        warnings.extend(mono.pop("warnings", []))

    rep["deltas"] = {
        "lufs": round(m_out["lufs_i"] - m_in["lufs_i"], 2),
        "true_peak": round(m_out["true_peak_dbfs"] - m_in["true_peak_dbfs"], 2),
        "lra": (round(m_out["lra"] - m_in["lra"], 2)
                if m_in.get("lra") is not None and m_out.get("lra") is not None
                else None),
    }
    rep["warnings"] = warnings
    rep["tool"] = "ffmpeg ebur128 + alimiter; gain in numpy (loudnorm not used: resamples to 192k)"
    return out, rep


def print_report(rep, dry_run=False):
    i, o = rep["input_measured"], rep.get("output_measured")
    w = sys.stderr
    print("", file=w)
    print("  %-22s %10s %10s" % ("", "in", "out" if o and not dry_run else "predicted"), file=w)
    if o and not dry_run:
        print("  %-22s %9.1f %10.1f  LUFS" % ("integrated loudness", i["lufs_i"], o["lufs_i"]), file=w)
        print("  %-22s %9.1f %10.1f  dBTP" % ("true peak", i["true_peak_dbfs"], o["true_peak_dbfs"]), file=w)
        if i.get("lra") is not None and o.get("lra") is not None:
            print("  %-22s %9.1f %10.1f  LU" % ("loudness range", i["lra"], o["lra"]), file=w)
    else:
        print("  %-22s %9.1f %10.1f  LUFS" % ("integrated loudness", i["lufs_i"], rep["target"]["lufs_i"]), file=w)
        print("  %-22s %9.1f %10.1f  dBTP" % ("true peak", i["true_peak_dbfs"], rep["gain"]["predicted_true_peak_dbfs"]), file=w)
    print("  %-22s %+9.2f  dB" % ("gain applied", rep["gain"]["applied_db"]), file=w)
    lim = rep["limiter"]
    if lim.get("engaged"):
        print("  %-22s %9s  worst %.2f dB, %.1f%% of file"
              % ("limiter", "engaged", lim["gr_max_db"], lim["limited_pct"]), file=w)
    else:
        print("  %-22s %9s" % ("limiter", "not engaged"), file=w)
    if rep["eq"]["mode"] != "none":
        print("  %-22s %+9.2f dB low, %+.2f dB high"
              % ("shelves", rep["eq"]["low_shelf_db"], rep["eq"]["high_shelf_db"]), file=w)
    if "mono" in rep:
        m = rep["mono"]
        print("  %-22s corr %.2f, bass corr %.2f, mono sum %.1f LU"
              % ("mono compatibility", m["correlation"] or 0,
                 m["bass_correlation"] or 0, m["mono_sum_loss_lu"] or 0), file=w)
    for warn in rep["warnings"]:
        print("  WARN  %s" % warn, file=w)
    print("", file=w)


# --------------------------------------------------------------------------
# selftest: arithmetic ground truth, no real audio, no ears.
#
# A dual-mono 1 kHz sine of amplitude A measures exactly 20*log10(A) LUFS on
# this build -- the -3 dB sine RMS and the +3 dB dual-mono channel sum cancel,
# and K-weighting is ~0 dB at 1 kHz. Everything below is anchored to that.
# --------------------------------------------------------------------------

def _sine(amp, secs=10.0, freq=1000.0):
    t = np.arange(int(SR * secs)) / SR
    s = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(s[:, None], 2, axis=1)


def _master(buf, **kw):
    kw.setdefault("target_lufs", DEFAULT_LUFS)
    kw.setdefault("ceiling_dbfs", DEFAULT_TP)
    kw.setdefault("limit_mode", "limit")
    kw.setdefault("eq_mode", "none")
    kw.setdefault("low_shelf_db", 0.0)
    kw.setdefault("high_shelf_db", 0.0)
    kw.setdefault("eq_limit", EQ_LIMIT)
    kw.setdefault("reference", None)
    kw.setdefault("max_limiting_pct", MAX_LIMITING_PCT)
    return master(buf, **kw)


def selftest() -> int:
    ok = True

    def check(label, passed, detail=""):
        nonlocal ok
        print("  %s  %s%s" % ("OK  " if passed else "FAIL", label,
                              ("   -> " + detail) if detail and not passed else ""))
        if not passed:
            ok = False

    print("Measurement anchors")
    m = L.measure(_sine(0.3535))
    check("dual-mono 1k sine @0.3535 measures -9.0 LUFS",
          abs(m["lufs_i"] + 9.0) < 0.15, "got %.2f" % m["lufs_i"])
    check("...and -9.0 dBTP",
          abs(m["true_peak_dbfs"] + 9.0) < 0.15, "got %.2f" % m["true_peak_dbfs"])
    m2 = L.measure(L.apply_gain(_sine(0.3535), 6.0))
    check("+6 dB gain lands at -3.0 LUFS",
          abs(m2["lufs_i"] + 3.0) < 0.15, "got %.2f" % m2["lufs_i"])
    m3 = L.measure(L.ffmpeg_filter(_sine(0.3535), "anull"))
    check("ffmpeg pipe is level-transparent (no 1/sqrt(2) upmix)",
          abs(m3["lufs_i"] + 9.0) < 0.15, "got %.2f" % m3["lufs_i"])

    print("Gain staging")
    _, r = _master(_sine(0.3535), target_lufs=-9.0, do_mono=False)
    check("already at target -> ~0 dB gain", abs(r["gain"]["applied_db"]) < 0.15,
          "got %.2f" % r["gain"]["applied_db"])
    check("...and limiter not engaged", not r["limiter"]["engaged"])
    _, r = _master(_sine(0.1), target_lufs=-9.0, do_mono=False)
    check("quiet source gains up by +11.0 dB",
          abs(r["gain"]["applied_db"] - 11.0) < 0.2, "got %.2f" % r["gain"]["applied_db"])
    check("...output lands on target",
          abs(r["output_measured"]["lufs_i"] + 9.0) < 0.2,
          "got %.2f" % r["output_measured"]["lufs_i"])
    _, r = _master(_sine(0.9), target_lufs=-9.0, do_mono=False)
    check("loud source gains down by -8.1 dB",
          abs(r["gain"]["applied_db"] + 8.1) < 0.2, "got %.2f" % r["gain"]["applied_db"])

    print("True-peak ceiling")
    spiky = _sine(0.1)
    for i in range(5):
        spiky[SR * (i + 1):SR * (i + 1) + 40] = 0.99
    out, r = _master(spiky, target_lufs=-9.0, ceiling_dbfs=-1.0, do_mono=False)
    check("limiter engages when the ceiling is threatened", r["limiter"]["engaged"])
    check("gain reduction is reported as a number",
          r["limiter"].get("gr_max_db", 0) < 0)
    check("re-measured true peak respects the ceiling",
          r["output_measured"]["true_peak_dbfs"] <= -1.0 + 0.05,
          "got %.2f" % r["output_measured"]["true_peak_dbfs"])
    check("inter-sample overshoot triggered one corrective pass",
          r["limiter"].get("corrective_pass_db") is not None)
    _, r = _master(spiky, target_lufs=-9.0, ceiling_dbfs=-1.0,
                   limit_mode="reduce", do_mono=False)
    check("--limit-mode reduce holds the ceiling without limiting",
          not r["limiter"]["engaged"]
          and r["output_measured"]["true_peak_dbfs"] <= -1.0 + 0.05,
          "engaged=%s tp=%.2f" % (r["limiter"]["engaged"],
                                  r["output_measured"]["true_peak_dbfs"]))

    print("Loudness convergence")
    # Dense material plus a hard ceiling: a single feed-forward gain undershoots,
    # so the solver must re-measure. Noise at -20 LUFS with a -1 dBTP ceiling.
    rng0 = np.random.default_rng(7)
    dense = (rng0.standard_normal((SR * 12, 2)) * 0.03).astype(np.float32)
    _, r = _master(dense, target_lufs=-12.0, ceiling_dbfs=-4.5,
                   max_limiting_pct=100.0, do_mono=False)
    check("lands on target with the limiter engaged",
          abs(r["output_measured"]["lufs_i"] + 12.0) <= 0.2
          and r["limiter"]["engaged"],
          "got %.2f, engaged=%s" % (r["output_measured"]["lufs_i"],
                                    r["limiter"]["engaged"]))
    # A ceiling this low means limiting absorbs the gain faster than the solver
    # can add it -- the case where chasing the number destroys the dynamics.
    _, r = _master(dense, target_lufs=-12.0, ceiling_dbfs=-6.0,
                   max_limiting_pct=5.0, do_mono=False)
    check("cost cap stops the chase and says so",
          any("stopped" in w for w in r["warnings"]),
          "warnings: %s" % r["warnings"])

    print("Idempotence")
    out, _ = _master(_sine(0.1), target_lufs=-9.0, do_mono=False)
    _, r2 = _master(out, target_lufs=-9.0, do_mono=False)
    check("mastering the master applies ~0 dB", abs(r2["gain"]["applied_db"]) < 0.2,
          "got %.2f" % r2["gain"]["applied_db"])
    check("...and does not re-engage the limiter", not r2["limiter"]["engaged"])

    print("Mono compatibility")
    r = L.mono_compat(_sine(0.3))
    check("L=R -> correlation +1.00", abs((r["correlation"] or 0) - 1.0) < 0.02)
    check("L=R -> mono sum loses 0.0 LU", abs(r["mono_sum_loss_lu"]) < 0.15)
    rng = np.random.default_rng(0)
    n = (rng.standard_normal((SR * 10, 2)) * 0.05).astype(np.float32)
    r = L.mono_compat(n)
    check("decorrelated -> correlation ~0.00", abs(r["correlation"] or 0) < 0.05)
    check("decorrelated -> mono sum loses ~3.0 LU",
          abs((r["mono_sum_loss_lu"] or 0) + 3.0) < 0.4,
          "got %.2f" % (r["mono_sum_loss_lu"] or 0))
    s = _sine(0.3)
    r = L.mono_compat(np.stack([s[:, 0], -s[:, 0]], axis=1))
    check("inverted -> correlation -1.00", abs((r["correlation"] or 0) + 1.0) < 0.02)
    check("inverted -> mono sum collapses", (r["mono_sum_loss_lu"] or 0) < -20)

    print("No resampling")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.wav"
        out, _ = _master(_sine(0.3535), do_mono=False)
        sf.write(str(p), out, SR, subtype="PCM_24")
        info = sf.info(str(p))
        check("output stays at 44100 Hz", info.samplerate == SR,
              "got %d" % info.samplerate)
        check("output is 24-bit", "24" in info.subtype, "got %s" % info.subtype)

    print("\nAll good." if ok else "\nSelftest failed.")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--out")
    ap.add_argument("--profile", default=None,
                    help="delivery profile: device (default, laptops and work "
                         "speakers) or club (PA and subs). See --list-profiles")
    ap.add_argument("--list-profiles", action="store_true")
    # These default to None so an explicit flag can be told apart from a
    # profile value; the profile fills in whatever the user did not pass.
    ap.add_argument("--lufs", type=float, default=None)
    ap.add_argument("--tp", type=float, default=None)
    ap.add_argument("--limit-mode", choices=["limit", "reduce", "off"], default="limit")
    ap.add_argument("--eq", choices=["none", "shelf", "match", "curve"], default="none",
                    help="curve = published genre tilt (references/tilt.json); "
                         "match = a wav you chose; shelf = your own numbers")
    ap.add_argument("--reference", help="wav to match band balance against (--eq match)")
    ap.add_argument("--low-shelf-db", type=float, default=0.0)
    ap.add_argument("--high-shelf-db", type=float, default=0.0)
    ap.add_argument("--eq-limit", type=float, default=EQ_LIMIT)
    ap.add_argument("--max-limiting-pct", type=float, default=None,
                    help="stop chasing the loudness target past this much "
                         "of the file being limited (default 60)")
    ap.add_argument("--tracklist", help="tracklist json to carry forward and annotate")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--dry-run", action="store_true",
                    help="measure and predict; write no audio")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.list_profiles:
        print(describe_profiles())
        return 0

    prof_spec = load_profiles()
    prof_name = args.profile or prof_spec.get("default", "device")
    prof, _ = resolve_profile(prof_name)
    # Explicit flags beat the profile; the profile beats the built-in default.
    target_lufs = args.lufs if args.lufs is not None else prof["lufs"]
    ceiling = args.tp if args.tp is not None else prof["tp"]
    max_lim = (args.max_limiting_pct if args.max_limiting_pct is not None
               else prof.get("max_limiting_pct", MAX_LIMITING_PCT))
    overrides = [n for n, v in (("--lufs", args.lufs), ("--tp", args.tp),
                                ("--max-limiting-pct", args.max_limiting_pct))
                 if v is not None]

    if not args.inp:
        ap.error("--in is required (or use --selftest)")
    if args.eq == "match" and not args.reference:
        ap.error("--eq match requires --reference")
    if not args.dry_run and not args.out:
        ap.error("--out is required unless --dry-run")

    src = Path(args.inp)
    buf, sr = sf.read(str(src), dtype="float32", always_2d=True)
    if sr != SR:
        raise SystemExit("%s: expected %d Hz, got %d" % (src.name, SR, sr))

    reference = None
    if args.reference:
        reference, rsr = sf.read(str(args.reference), dtype="float32", always_2d=True)
        if rsr != SR:
            raise SystemExit("reference: expected %d Hz, got %d" % (SR, rsr))

    out, rep = master(
        buf, target_lufs=target_lufs, ceiling_dbfs=ceiling,
        limit_mode=args.limit_mode, eq_mode=args.eq,
        low_shelf_db=args.low_shelf_db, high_shelf_db=args.high_shelf_db,
        eq_limit=args.eq_limit, reference=reference,
        max_limiting_pct=max_lim,
        do_mono=not args.dry_run,
    )
    rep["input"] = {"file": str(src)}
    rep["profile"] = {"name": prof_name, "summary": prof.get("summary"),
                      "overridden": overrides or None}

    if args.dry_run:
        rep["dry_run"] = True
        print_report(rep, dry_run=True)
        print(json.dumps(rep, indent=2, default=_jsonable))
        return 0

    dst = Path(args.out)
    sf.write(str(dst), out, SR, subtype="PCM_24")
    rep["output"] = {"file": str(dst), "subtype": "PCM_24", "samplerate": SR}
    print_report(rep)

    if args.tracklist:
        tl_path = Path(args.tracklist)
        tl = json.loads(tl_path.read_text(encoding="utf-8"))
        if "master" in tl:
            print("  WARN  %s already carries a master block; overwriting"
                  % tl_path.name, file=sys.stderr)
        # Load and mutate, never rebuild: that is what preserves order_rationale
        # and anything else added by hand.
        tl["output"] = str(dst)
        tl["master"] = rep
        dst.with_suffix(".tracklist.json").write_text(
            json.dumps(tl, indent=2, default=_jsonable), encoding="utf-8")

    json_path = Path(args.json_out) if args.json_out else dst.with_suffix(".master.json")
    json_path.write_text(json.dumps(rep, indent=2, default=_jsonable), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
