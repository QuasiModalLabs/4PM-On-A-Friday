#!/usr/bin/env python3
"""Render a beat-reactive visualiser with review text over a mix.

Every frame is computed FROM the audio at that timestamp, so sync is exact by
construction -- there is nothing to drift. No generated video, no manual keying.

Layout: kick-reactive hook text centred, log-spaced spectrum bars beneath,
source review text at the bottom, progress bar and track marker at the edges.

Usage:
    python3 visualize.py --audio mix.wav --tracklist mix.tracklist.json \
        --text text.json --out video.mp4 [--size 1080] [--fps 30]

text.json (optional -- falls back to titles from the tracklist):
{
  "tracks": [
    {"title": "...", "hook": "Don't bother.", "review": "full review text"}
  ]
}
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

# Font candidates per role, tried in order. Covers Linux, Windows, and macOS --
# the visualiser must not be Linux-only.
FONT_CANDIDATES = {
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
    "mono": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    ],
}
BG = (8, 8, 10)
FG = (240, 240, 245)
DIM = (110, 110, 120)
ACCENT = (255, 62, 62)

N_BARS = 48


def load_font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """First candidate that exists wins. Falls back to PIL's bitmap font, which
    renders but looks bad -- warn rather than fail silently."""
    for cand in FONT_CANDIDATES.get(role, []):
        if Path(cand).exists():
            return ImageFont.truetype(cand, size)
    print(f"  WARNING: no '{role}' font found; falling back to a default font. "
          f"Output will look poor.", file=sys.stderr)
    return ImageFont.load_default()


def compute_features(y: np.ndarray, sr: int, fps: int) -> dict:
    """Per-video-frame audio features. One row per rendered frame."""
    hop = int(sr / fps)
    n_frames = len(y) // hop

    win = 2048
    window = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1 / sr)

    # Log-spaced band edges, 40 Hz to 16 kHz.
    edges = np.logspace(np.log10(40), np.log10(16000), N_BARS + 1)
    band_idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0]
                for i in range(N_BARS)]

    kick = np.zeros(n_frames, dtype=np.float32)
    rms = np.zeros(n_frames, dtype=np.float32)
    bars = np.zeros((n_frames, N_BARS), dtype=np.float32)

    for i in range(n_frames):
        s = i * hop
        seg = y[s:s + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        rms[i] = np.sqrt(np.mean(seg ** 2))
        spec = np.abs(np.fft.rfft(seg * window))
        # Kick band: 40-110 Hz. In hardstyle this is essentially a beat clock.
        kick[i] = np.mean(spec[(freqs >= 40) & (freqs < 110)])
        for b, idx in enumerate(band_idx):
            bars[i, b] = np.mean(spec[idx]) if len(idx) else 0.0

    def norm(a, pct=99.0):
        p = np.percentile(a, pct)
        return np.clip(a / p, 0, 1.4) if p > 0 else a

    def follow(x, attack_s=0.012, release_s=0.45):
        """Fast-attack, slow-release envelope over the kick.

        The raw per-frame kick figure is noisy: inside one drop it crosses any
        given level several times per beat, so anything driving size or colour
        straight from it chatters rather than pulses -- measured at 51 changes
        against 15 beats in six seconds. Snapping up on the hit and easing down
        after it turns that into one movement per kick, which is what the eye
        reads as being in time.

        Attack stays very short so the visual still lands ON the transient. A
        slow attack would fix the chatter by making everything late, which is
        the failure this is meant to remove.

        Release was tuned by measurement, not taste: swept against direction
        reversals per beat, where a clean pulse is 2.0 -- one rise, one fall.
        Raw kick measures 4.6-5.7 across three sections of a real set; 0.18 s
        gives 3.5; 0.45 s gives 2.11 with the peak still landing on the beat
        and the modulation depth intact. It is longer than a beat at 152 BPM,
        which is the point -- the hook breathes rather than flickering.
        """
        a_att = float(np.exp(-1.0 / max(attack_s * fps, 1e-6)))
        a_rel = float(np.exp(-1.0 / max(release_s * fps, 1e-6)))
        out = np.zeros_like(x)
        prev = 0.0
        for j, v in enumerate(x):
            a = a_att if v > prev else a_rel
            prev = a * prev + (1.0 - a) * float(v)
            out[j] = prev
        return out

    bars = np.log1p(bars * 8)
    bars = bars / max(np.percentile(bars, 99.5), 1e-9)

    kick_n = norm(kick)
    return {
        "n_frames": n_frames,
        "kick": kick_n,
        "pulse": follow(kick_n),
        "rms": norm(rms),
        "bars": np.clip(bars, 0, 1.3),
    }


def wrap(draw, text, font, max_w) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# How each hardstyle variant moves. One table, one draw routine -- five bespoke
# effects would drift apart and stop looking like one design.
#
# Restrained on purpose: jitter tops out at 3 px and channel split at 4 px on a
# 1080 frame, fractions of a percent of the width. The set has to survive ten
# minutes, and an effect that reads as a gimmick on track one is unwatchable by
# track five. All pixel figures are per 1080 and scale with size.
#
#   jitter    px of per-frame displacement, deterministic, kick-weighted
#   split     px of red/blue channel offset -- the glitch
#   pulse     extra scale at full kick, e.g. 0.04 = 4% bigger on the beat
#   warm      shadow colour: warm amber rather than the red used for raw
#   double    second, wider shadow -- reads as bloom when warm, as grit when red
#   kick_gate motion only above this kick level, so it hits rather than shimmers.
#             Set it low: jitter is already multiplied by kick energy, so the
#             gate is a floor for silence, not the thing shaping the movement.
#             A high gate on sparse material makes the loudest variant the
#             stillest one, which is exactly backwards.
EFFECTS = {
    "euphoric":    {"jitter": 0.0, "split": 0.0, "pulse": 0.035, "warm": True,
                    "double": True,  "kick_gate": 0.0},
    "melodic":     {"jitter": 0.0, "split": 0.0, "pulse": 0.02, "warm": True,
                    "double": False, "kick_gate": 0.0},
    "raw-melodic": {"jitter": 1.0, "split": 1.0, "pulse": 0.03, "warm": False,
                    "double": False, "kick_gate": 0.0},
    "raw":         {"jitter": 2.0, "split": 3.0, "pulse": 0.0,  "warm": False,
                    "double": False, "kick_gate": 0.0},
    "uptempo":     {"jitter": 3.0, "split": 4.0, "pulse": 0.05, "warm": False,
                    "double": True,  "kick_gate": 0.35},
}
DEFAULT_VARIANT = "melodic"
GLOW_STEP = 8          # quantisation of the kick glow; see _tinted
SCALE_STEPS = 24       # levels across a variant's pulse range

# Step 2 of review-to-hardstyle maps tone to variant, and each variant to a BPM
# band. Read backwards, a track's original BPM is a usable guess at its variant
# -- which is what makes this work on a text.json written before `variant`
# existed. Bands are the upper bound of each; anything faster is uptempo.
BPM_BANDS = [(152, "euphoric"), (155, "melodic"), (157, "raw-melodic"),
             (160, "raw")]


def variant_for(seg: dict) -> str:
    """Which variant drives this track's hook, in order of authority.

    1. an explicit "effect" on the entry -- a deliberate override
    2. "variant", written by review-to-hardstyle from the review's tone
    3. the track's original BPM, read back through Step 2's own bands
    4. the default

    The tone call is judgement made upstream while reading the review. Deriving
    it from the audio would be re-deriving something already decided, and worse:
    BPM only separates the variants because Step 2 assigned the tempos in the
    first place.
    """
    for key in ("effect", "variant"):
        v = seg.get(key)
        if isinstance(v, str) and v.strip().lower() in EFFECTS:
            return v.strip().lower()
    bpm = seg.get("original_bpm")
    if isinstance(bpm, (int, float)):
        for limit, name in BPM_BANDS:
            if bpm <= limit:
                return name
        return "uptempo"
    return DEFAULT_VARIANT


def effect_params(seg: dict, size: int) -> dict:
    """EFFECTS row for this segment, with pixel figures scaled to the frame."""
    p = dict(EFFECTS[variant_for(seg)])
    scale = size / 1080.0
    p["jitter"] *= scale
    p["split"] *= scale
    return p


def frame_jitter(i: int, amount: float) -> tuple[float, float]:
    """Displacement for frame i. A pure function of i, never global random.

    Renders have to be reproducible: the same mix rendered twice must give the
    same file, or the 1-fps pre-flight stops describing the real render.
    """
    if amount <= 0:
        return 0.0, 0.0
    h = (i * 2654435761) & 0xFFFFFFFF          # Knuth multiplicative hash
    dx = ((h & 0xFFFF) / 65535.0) * 2.0 - 1.0
    dy = ((h >> 16) / 65535.0) * 2.0 - 1.0
    return dx * amount, dy * amount


_HOOK_CACHE: dict = {}


def hook_layer(hook: str, font, size: int, max_w: int) -> Image.Image:
    """The wrapped hook drawn once into an RGBA layer, cached per track.

    The hook does not change for the length of a track, but the old code redrew
    every line with d.text() on every frame. Drawing it once and compositing the
    result pays for the effects: the extra work per frame is a couple of pastes
    of an existing layer rather than fresh glyph rasterisation.
    """
    key = (hook, size, max_w, id(font))
    layer = _HOOK_CACHE.get(key)
    if layer is not None:
        return layer

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = wrap(probe, hook.upper(), font, max_w)
    lh = int(font.size * 1.15)
    w = max(int(probe.textlength(ln, font=font)) for ln in lines) if lines else 1
    layer = Image.new("RGBA", (max(w, 1), max(lh * len(lines), 1)), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    y = 0
    for ln in lines:
        ld.text(((layer.width - probe.textlength(ln, font=font)) / 2, y),
                ln, font=font, fill=(255, 255, 255, 255))
        y += lh
    _HOOK_CACHE[key] = layer
    return layer


_TINT_CACHE: dict = {}


def _tinted(layer: Image.Image, colour: tuple) -> Image.Image:
    """Recolour the cached white layer, keeping its alpha.

    Cached, because building these was the whole cost of the effect: up to five
    tinted copies per frame, each a full-width RGBA allocation. The colours that
    vary with kick energy are quantised (GLOW_STEP), so a track converges on a
    handful of distinct tints and the pastes become the only per-frame work.
    """
    key = (id(layer), colour)
    hit = _TINT_CACHE.get(key)
    if hit is not None:
        return hit
    solid = Image.new("RGBA", layer.size, colour + (255,))
    solid.putalpha(layer.getchannel("A"))
    _TINT_CACHE[key] = solid
    return solid


def draw_hook(img: Image.Image, layer: Image.Image, cx: int, top: int,
              k: float, p: dict, i: int) -> None:
    """Composite the hook with this variant's motion, shadow and split."""
    moving = k >= p["kick_gate"]
    if p["pulse"] > 0:
        # Quantised across THIS pulse's range, not across absolute scale. The
        # first version used 1/16 steps of absolute scale -- coarser than the
        # entire 0.02-0.08 pulse range, so every variant collapsed to one or
        # two sizes and the swell became a comparator that snapped between
        # them. That single bug produced both the popping and the apparent
        # loss of sync. SCALE_STEPS levels across the range keeps the cache
        # small while the movement stays continuous.
        step = round(k * SCALE_STEPS) / SCALE_STEPS * p["pulse"]
        scale = 1.0 + step
    else:
        step, scale = 0.0, 1.0
    if abs(scale - 1.0) > 1e-4:
        if abs(step) > 1e-6:
            key = ("scaled", id(layer), step)
            cached = _HOOK_CACHE.get(key)
            if cached is None:
                cached = layer.resize(
                    (max(1, int(layer.width * scale)),
                     max(1, int(layer.height * scale))), Image.BILINEAR)
                _HOOK_CACHE[key] = cached
            layer = cached

    # Weighted by kick, not flat. Flat jitter shimmers through breakdowns and
    # silence, which reads as a broken font rather than a reaction to anything;
    # weighting ties the movement to the thing it is supposed to be reacting to.
    jx, jy = frame_jitter(i, p["jitter"] * k if moving else 0.0)
    x = int(cx - layer.width / 2 + jx)
    y = int(top + jy)

    # Quantised so the tint cache actually hits. At 60 levels every frame
    # invented a new colour and rebuilt every layer; at 8 the step is invisible
    # and a track settles into a handful of cached tints.
    glow = int(k * 60) // GLOW_STEP * GLOW_STEP
    shadow = (min(255, 120 + glow), 90, 40) if p["warm"] \
        else (min(255, 90 + glow), 40, 40)

    if p["double"]:
        off = int(4 * (1 + k))
        img.paste(_tinted(layer, tuple(int(c * 0.55) for c in shadow)),
                  (x + off, y + off), layer)
    img.paste(_tinted(layer, shadow), (x + 2, y + 2), layer)

    split = p["split"] * (k if moving else 0.0)
    if split >= 1.0:
        s = int(split)
        img.paste(_tinted(layer, (200, 30, 30)), (x - s, y), layer)
        img.paste(_tinted(layer, (30, 60, 200)), (x + s, y), layer)

    body = (255, min(255, 200 + glow), min(255, 200 + glow))
    img.paste(_tinted(layer, body), (x, y), layer)


def render_frame(f: dict, i: int, size: int, seg: dict, fonts: dict,
                 t: float, total: float) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    k = float(f["kick"][i])
    # The hook follows the smoothed envelope; the bars keep the raw figure,
    # where per-frame detail is the point.
    hk = float(f.get("pulse", f["kick"])[i])
    pad = int(size * 0.07)

    # --- spectrum bars, mirrored around the centre line -----------------
    bar_zone_h = int(size * 0.13)
    bar_y = int(size * 0.70)
    bw = (size - pad * 2) / N_BARS
    for b in range(N_BARS):
        h = int(f["bars"][i, b] * bar_zone_h)
        if h < 1:
            continue
        x0 = pad + b * bw
        shade = int(90 + 165 * f["bars"][i, b])
        col = (shade, int(shade * 0.28), int(shade * 0.28)) if b < N_BARS * 0.25 \
            else (shade, shade, min(255, int(shade * 1.05)))
        d.rectangle([x0, bar_y - h, x0 + bw * 0.72, bar_y + h * 0.35], fill=col)

    # --- hook text: kick energy plus this track's variant ----------------
    hook = seg.get("hook") or seg.get("title", "")
    if hook:
        layer = hook_layer(hook, fonts["hook"], size, size - pad * 2)
        top = cy - layer.height // 2 - int(size * 0.14)
        draw_hook(img, layer, cx, top, hk, effect_params(seg, size), i)

    # --- source review, small, at the bottom ----------------------------
    review = seg.get("review", "")
    if review:
        rf = fonts["body"]
        # Fit as many lines as the band above the progress bar actually holds
        # -- 6 at 720, 5 at 1080. This was a fixed 4, which silently cut the
        # longest review mid-sentence at every render size, so drafting at 720
        # and rendering at 1080 could not reveal or fix it.
        lh = int(rf.size * 1.35)
        max_lines = max(1, (int(size * 0.958) - int(size * 0.79)) // lh)
        lines = wrap(d, f'"{review}"', rf, size - pad * 2)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(' "') + '..."'
        y = int(size * 0.79)
        for ln in lines:
            d.text((cx - d.textlength(ln, font=rf) / 2, y), ln, font=rf, fill=DIM)
            y += int(rf.size * 1.35)

    # --- track marker + progress ----------------------------------------
    label = f"{seg.get('position', 1):02d} — {seg.get('title', '')}"
    d.text((pad, pad), label.upper(), font=fonts["label"], fill=DIM)

    tc = f"{int(t)//60}:{int(t)%60:02d}"
    d.text((size - pad - d.textlength(tc, font=fonts["label"]), pad),
           tc, font=fonts["label"], fill=DIM)

    py = size - int(pad * 0.6)
    d.line([(pad, py), (size - pad, py)], fill=(38, 38, 44), width=3)
    d.line([(pad, py), (pad + (size - pad * 2) * (t / total), py)],
           fill=ACCENT, width=3)

    return img


def track_number(name: str) -> int | None:
    """Leading digits of a filename: '02-sums-up.wav' -> 2."""
    m = re.match(r"(\d+)", Path(name).name)
    return int(m.group(1)) if m else None


def merge_text(segs: list, extra: list, total: float) -> list:
    """Attach hooks and review text to tracklist segments, matched by filename.

    Matching is by file, not by position, because the running order is chosen at
    blend time and is deliberately not the 01-/02- download order that text.json
    is written in. Merging by index captions every track with the wrong hook the
    moment those two differ.

    Three ways to match, in order of preference:
      1. an explicit "file" key on the text.json entry
      2. the leading number of the tracklist filename, indexing text.json
         (entry i describes track i+1) -- this is what the folder convention means
      3. position, when there is nothing else to go on
    """
    if not extra:
        return segs

    # No tracklist to match against: lay the text out evenly and return.
    if not segs:
        return [{**e, "position": i + 1, "start_s": total * i / len(extra)}
                for i, e in enumerate(extra)]

    by_file = {Path(e["file"]).name: e for e in extra if e.get("file")}
    unmatched = []

    for i, sg in enumerate(segs):
        fname = Path(sg.get("file", "")).name
        e = by_file.get(fname)
        if e is None:
            n = track_number(fname)
            if n is not None and 1 <= n <= len(extra):
                e = extra[n - 1]
        if e is None and len(extra) == len(segs):
            e = extra[i]          # last resort: same length, assume position
        if e is None:
            unmatched.append(fname or f"segment {i + 1}")
            continue
        sg.update(e)

    if unmatched:
        print(f"warning: no text.json entry for {', '.join(unmatched)}; "
              "those tracks fall back to their title", file=sys.stderr)
    return segs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--tracklist")
    ap.add_argument("--text")
    ap.add_argument("--out", default="video.mp4")
    ap.add_argument("--size", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    y, sr = sf.read(args.audio, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    total = len(y) / sr

    segs = []
    if args.tracklist:
        tl = json.loads(Path(args.tracklist).read_text(encoding="utf-8"))
        segs = tl.get("tracklist", [])
    if args.text:
        extra = json.loads(
            Path(args.text).read_text(encoding="utf-8")).get("tracks", [])
        segs = merge_text(segs, extra, total)
    if not segs:
        segs = [{"position": 1, "title": Path(args.audio).stem, "start_s": 0.0}]

    print("computing audio features...", file=sys.stderr)
    f = compute_features(y, sr, args.fps)
    n = f["n_frames"]

    s = args.size
    fonts = {
        "hook": load_font("bold", int(s * 0.072)),
        "body": load_font("regular", int(s * 0.022)),
        "label": load_font("mono", int(s * 0.018)),
    }

    starts = [sg.get("start_s", 0.0) for sg in segs]

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{s}x{s}", "-r", str(args.fps), "-i", "-",
         "-i", args.audio,
         "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
         "-shortest", args.out],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    print(f"rendering {n} frames at {s}x{s}...", file=sys.stderr)
    for i in range(n):
        t = i / args.fps
        si = max(0, int(np.searchsorted(starts, t, side="right") - 1))
        proc.stdin.write(render_frame(f, i, s, segs[si], fonts, t, total).tobytes())
        if i % (args.fps * 30) == 0:
            print(f"  {t:.0f}s / {total:.0f}s", file=sys.stderr)

    proc.stdin.close()
    proc.wait()
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
