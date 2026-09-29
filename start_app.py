from __future__ import annotations
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
APP_NAME = "露天矿电铲样机控制台"
exe = ROOT / "dist" / APP_NAME / f"{APP_NAME}.exe"
if exe.exists():
    subprocess.Popen([str(exe)], cwd=exe.parent)
    raise SystemExit(0)
app = ROOT / "app.py"
subprocess.Popen([sys.executable, str(app)], cwd=ROOT)
