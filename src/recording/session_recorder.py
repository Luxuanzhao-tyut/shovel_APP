from __future__ import annotations

import csv
import json
import queue
import threading
import time
from pathlib import Path


class SessionRecorder:
    """把 DB400 采样帧异步写入 CSV。

    关键要求：PLC 轮询线程不能被磁盘 flush 阻塞。
    write_dict() 只负责把一帧放入内存队列；真正的 writerow/flush
    在独立后台线程中完成。close() 会等待队列写完并安全关闭文件。
    """

    _SENTINEL = object()

    def __init__(self, path: Path, fieldnames: list[str]):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() != '.csv':
            path = path.with_suffix('.csv')
        self.path = path
        self.fieldnames = list(dict.fromkeys(fieldnames))

        self._stream = path.open('x', newline='', encoding='utf-8-sig')
        self._writer = csv.DictWriter(
            self._stream,
            fieldnames=self.fieldnames,
            extrasaction='ignore'
        )
        self._writer.writeheader()
        self._stream.flush()

        self._queue: queue.Queue = queue.Queue()
        self._closed = False
        self._worker_error: Exception | None = None
        self._thread = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name='db400-csv-writer'
        )
        self._thread.start()

    def _normalize_row(self, values: dict) -> dict:
        row = {}
        for key in self.fieldnames:
            value = values.get(key, '')
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, ensure_ascii=False)
            elif value is None:
                value = ''
            row[key] = value
        return row

    def write_dict(self, values: dict) -> None:
        if self._closed:
            raise RuntimeError('记录器已关闭')
        if self._worker_error is not None:
            raise RuntimeError(f'CSV后台写入失败：{self._worker_error}')

        # 这里只做内存入队，不做磁盘 I/O。
        self._queue.put(self._normalize_row(values))

    def _writer_loop(self) -> None:
        pending = 0
        last_flush = time.monotonic()
        try:
            while True:
                try:
                    item = self._queue.get(timeout=0.25)
                except queue.Empty:
                    item = None

                if item is self._SENTINEL:
                    self._queue.task_done()
                    break

                if item is not None:
                    self._writer.writerow(item)
                    pending += 1
                    self._queue.task_done()

                now = time.monotonic()
                # 批量/定时 flush；flush 只发生在后台线程。
                if pending and (pending >= 20 or now - last_flush >= 1.0):
                    self._stream.flush()
                    pending = 0
                    last_flush = now

            # 关闭前把队列中已经入队的数据全部写完。
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not self._SENTINEL:
                    self._writer.writerow(item)
                self._queue.task_done()

            self._stream.flush()

        except Exception as exc:
            self._worker_error = exc
        finally:
            try:
                self._stream.flush()
            except Exception:
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        self._queue.put(self._SENTINEL)
        self._thread.join(timeout=5.0)

        if self._thread.is_alive():
            raise RuntimeError('CSV后台写线程未能在5秒内结束')

        if not self._stream.closed:
            self._stream.close()

        if self._worker_error is not None:
            raise RuntimeError(f'CSV后台写入失败：{self._worker_error}')
