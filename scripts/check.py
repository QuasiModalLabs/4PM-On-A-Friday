#!/usr/bin/env python3
"""Verify the environment before running anything. Run this first.

  Windows : python scripts\\check.py
  mac/Linux: python3 scripts/check.py
"""
import platform
import shutil
import sys
from pathlib import Path

ok = True
WIN = platform.system() == "Windows"
PIP = "pip install -r requirements.txt" + ("" if WIN else " --break-system-packages")


def check(label, passed, hint=""):
    global ok
    print(f"  {'OK  ' if passed else 'FAIL'}  {label}")
    if not passed:
        ok = False
        if hint:
            print(f"          -> {hint}")


print(f"Platform: {platform.system()} {platform.release()}, Python {sys.version.split()[0]}\n")

for mod in ["librosa", "soundfile", "numpy", "PIL", "pandas"]:
    try:
        __import__(mod)
        check(mod, True)
    except ImportError:
        check(mod, False, PIP)

check("ffmpeg", shutil.which("ffmpeg") is not None,
      "winget install Gyan.FFmpeg   (then restart your terminal)" if WIN
      else "apt install ffmpeg   /   brew install ffmpeg")

FONTS = {
    "bold":    ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
    "regular": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "mono":    ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
                "C:/Windows/Fonts/consolab.ttf", "/System/Library/Fonts/Menlo.ttc",
                "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"],
}
for role, cands in FONTS.items():
    found = next((c for c in cands if Path(c).exists()), None)
    check(f"font: {role}", found is not None,
          "visualiser falls back to a default font; output will look poor")

for d in ["input", "tracks", "output", "docs", "config"]:
    check(f"{d}/ exists", Path(d).is_dir(), f"mkdir {d}")

print("\nAll good." if ok else "\nFix the above before running the pipeline.")
sys.exit(0 if ok else 1)
