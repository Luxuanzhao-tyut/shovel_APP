"""
把 ShovelState 追加到新 CSV；输入状态，输出 CSV 文件路径。
不连接 MySQL 或 PLC，None 留空并保留 errors/source 防止误读。
增加记录格式或持久化策略时修改；默认独占创建，绝不覆盖历史记录。
"""
import csv
import json
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from models.shovel_state import ShovelState


class CSVRecorder:
    """单进程逐行写入，每条 flush；不承诺断电后的磁盘持久性。"""

    def __init__(self, directory: Path, filename: str | None = None):
        """创建带微秒时间戳的新文件；同名存在则抛 FileExistsError。"""
        directory.mkdir(parents=True, exist_ok=True)
        filename = filename or datetime.now().strftime('plc_record_%Y%m%d_%H%M%S_%f.csv')
        if Path(filename).name != filename or not filename.endswith('.csv'):
            raise ValueError('filename 必须是单个 CSV 文件名')
        self.path = directory / filename
        self._stream = self.path.open('x', newline='', encoding='utf-8-sig')
        self._writer = csv.DictWriter(self._stream, fieldnames=[item.name for item in fields(ShovelState)])
        self._writer.writeheader()
        self._stream.flush()

    def write(self, state: ShovelState) -> None:
        """记录统一状态；错误字典转 JSON，未知数值保持空单元格。"""
        row = asdict(state)
        row['errors'] = json.dumps(row['errors'], ensure_ascii=False)
        row['additional_values'] = json.dumps(row['additional_values'], ensure_ascii=False)
        self._writer.writerow(row)
        self._stream.flush()

    def close(self) -> None:
        """关闭文件，不改变已记录内容。"""
        self._stream.close()

    def __enter__(self):
        """供 with 语句管理文件生命周期。"""
        return self

    def __exit__(self, exc_type, exc, traceback):
        """正常退出、异常或 Ctrl+C 时都关闭文件。"""
        self.close()
