"""
线程安全的 snap7 客户端封装。
读取始终允许（连接成功后）；写入只有在运行时安全会话显式把 write_enabled=True 且 dry_run=False 后才开放。
所有 snap7 I/O 经同一 RLock 串行化，避免 10 Hz 心跳、DB400 轮询和 UI 命令并发访问同一 Client。
"""
from __future__ import annotations

import threading


class S7Client:
    """单 PLC 连接；内部串行化 snap7 read/write。"""

    def __init__(self, config: dict):
        self.config = config
        self._client = None
        self._io_lock = threading.RLock()

    def connect(self) -> None:
        notes = self.config['source_notes']
        if notes.get('ip_status') == 'UNRESOLVED_CONFLICT' or notes.get('site_ip_confirmed') is not True:
            raise RuntimeError('PLC IP 来源冲突尚未人工确认；拒绝连接')
        if self._client is not None:
            self.disconnect()
        import snap7
        with self._io_lock:
            self._client = snap7.client.Client()
            try:
                plc = self.config['plc']
                self._client.connect(plc['active_ip'], plc['rack'], plc['slot'])
                if not self.is_connected():
                    raise ConnectionError('PLC 未建立连接')
            except Exception:
                self.disconnect()
                raise

    def disconnect(self) -> None:
        with self._io_lock:
            if self._client is not None:
                try:
                    self._client.disconnect()
                finally:
                    try:
                        self._client.destroy()
                    finally:
                        self._client = None

    def is_connected(self) -> bool:
        with self._io_lock:
            return self._client is not None and bool(self._client.get_connected())

    def read_bytes(self, db: int, byte_offset: int, size: int) -> bytes:
        if any(type(v) is not int or v < 0 for v in (db, byte_offset, size)) or size == 0:
            raise ValueError('非法 DB/偏移/长度')
        with self._io_lock:
            if self._client is None or not bool(self._client.get_connected()):
                raise ConnectionError('PLC 离线')
            data = bytes(self._client.db_read(db, byte_offset, size))
        if len(data) != size:
            raise IOError(f'PLC 短读：预期 {size}，实际 {len(data)}')
        return data

    def write_bytes(self, db: int, byte_offset: int, data: bytes) -> None:
        """最低写入口。

        这里只检查“当前会话是否已经由 LiveControlManager 武装”。机构联锁在上层做；
        未武装时，即使调用者直接碰到本函数也会 fail-closed。
        """
        if type(db) is not int or db < 0 or type(byte_offset) is not int or byte_offset < 0:
            raise ValueError('非法 DB/偏移')
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise ValueError('写入数据必须是非空 bytes')
        safety = self.config['safety']
        if safety.get('write_enabled') is not True or safety.get('dry_run') is not False:
            raise RuntimeError('真实写入拒绝：当前会话未武装')
        with self._io_lock:
            if self._client is None or not bool(self._client.get_connected()):
                raise ConnectionError('PLC 离线')
            self._client.db_write(db, byte_offset, bytearray(data))
