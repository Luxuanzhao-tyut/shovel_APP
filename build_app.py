from __future__ import annotations
import os
import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "露天矿电铲样机控制台"
PY = Path(sys.executable)

def run(args, **kwargs):
    print("+", " ".join(map(str, args)))
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True, **kwargs)

os.environ["PYTHONPATH"] = str(ROOT / "src")
print("Running tests...")
run([PY, "-m", "pytest", "-q"])

print("Building application...")
sep = ";" if os.name == "nt" else ":"
run([
    PY, "-m", "PyInstaller",
    "--noconfirm", "--clean", "--windowed", "--onedir",
    "--name", APP_NAME,
    "--paths", "src",
    "--hidden-import", "snap7",
    "--add-data", f"config{sep}config",
    "app.py",
])
app_dir = ROOT / "dist" / APP_NAME
exe = app_dir / f"{APP_NAME}.exe"
# 复制可编辑配置到 EXE 同级目录；程序优先读取这里。
shutil.copytree(ROOT / "config", app_dir / "config", dirs_exist_ok=True)
print("Build completed successfully.")
print("EXE:", exe)
print("Editable settings:", app_dir / "config" / "operator_settings.yaml")
