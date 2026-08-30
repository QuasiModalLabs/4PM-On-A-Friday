#!/usr/bin/env python3
r"""Verify the environment before running anything. Run this first.

  Windows : .venv\Scripts\activate.bat   then   python scripts\check.py
  mac/Linux: source .venv/bin/activate     then   python3 scripts/check.py

Activate first. Installing from the wrong interpreter is the most common way to
get a passing pip install and a failing pipeline.
"""
import platform
import shutil
import sys
from pathlib import Path

ok = True
WIN = platform.system() == "Windows"

IN_VENV = sys.prefix != sys.base_prefix
PROJECT_VENV = Path(__file__).resolve().parent.parent / ".venv"
STRAY_VENV = PROJECT_VENV.is_dir() and not IN_VENV
ACTIVATE = r".venv\Scripts\activate.bat" if WIN else "source .venv/bin/activate"

# --break-system-packages is for a deliberate global install on a PEP 668
# distro. Inside a venv it is wrong; on Windows it does not apply. And if this
# project has a .venv that just isn't active, installing is not the fix at all.
if STRAY_VENV:
    PIP = f"{ACTIVATE}   then   pip install -r requirements.txt"
else:
    PIP = "pip install -r requirements.txt" + (
        "" if WIN or IN_VENV else " --break-system-packages")


def check(label, passed, hint=""):
    global ok
    print(f"  {'OK  ' if passed else 'FAIL'}  {label}")
    if not passed:
        ok = False
        if hint:
            print(f"          -> {hint}")


print(f"Platform: {platform.system()} {platform.release()}, Python {sys.version.split()[0]}")
print(f"Interpreter: {sys.executable}\n")

if IN_VENV:
    check("virtualenv active", True)
elif STRAY_VENV:
    check("virtualenv active", False,
          f"a .venv exists here but is not active. Run:  {ACTIVATE}")
else:
    print("  --    virtualenv active (none here; installing globally)")

for mod in ["librosa", "soundfile", "numpy", "PIL", "pandas", "openpyxl"]:
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
