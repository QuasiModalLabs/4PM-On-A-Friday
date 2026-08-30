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

    bars = np.log1p(bars * 8)
    bars = bars / max(np.percentile(bars, 99.5), 1e-9)

    return {
        "n_frames": n_frames,
        "kick": norm(kick),
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


def render_frame(f: dict, i: int, size: int, seg: dict, fonts: dict,
                 t: float, total: float) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    k = float(f["kick"][i])
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

    # --- hook text, scaled by kick energy -------------------------------
    hook = seg.get("hook") or seg.get("title", "")
    if hook:
        base = fonts["hook"]
        lines = wrap(d, hook.upper(), base, size - pad * 2)
        lh = int(base.size * 1.15)
        y = cy - (len(lines) * lh) // 2 - int(size * 0.14)
        glow = int(k * 60)
        for ln in lines:
            w = d.textlength(ln, font=base)
            x = cx - w / 2
            if glow > 8:
                d.text((x + 2, y + 2), ln, font=base,
                       fill=(min(255, 90 + glow), 40, 40))
            d.text((x, y), ln, font=base,
                   fill=(255, min(255, 200 + glow), min(255, 200 + glow)))
            y += lh

    # --- source review, small, at the bottom ----------------------------
    review = seg.get("review", "")
    if review:
        rf = fonts["body"]
        lines = wrap(d, f'"{review}"', rf, size - pad * 2)[:4]
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
        tl = json.loads(Path(args.tracklist).read_text())
        segs = tl.get("tracklist", [])
    if args.text:
        extra = json.loads(Path(args.text).read_text()).get("tracks", [])
        for i, e in enumerate(extra):
            if i < len(segs):
                segs[i].update(e)
            else:
                segs.append({**e, "position": i + 1, "start_s": total * i / len(extra)})
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
