from __future__ import annotations
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
# V2.3 源码版：不要优先启动压缩包中旧的 V2.2 EXE，否则新轨迹控制器不会生效。
# 待在 Windows 上重新运行 build_app.py 后，可再直接使用新生成的 EXE。
app = ROOT / "app.py"
subprocess.Popen([sys.executable, str(app)], cwd=ROOT)
