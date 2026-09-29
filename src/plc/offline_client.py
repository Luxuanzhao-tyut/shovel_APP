"""
离线只读缓冲区：输入按 DB 编号分组的测试字节，输出与 read_bytes 相同形状的字节。
不导入 snap7、不提供 connect 或写方法；仅供教学与离线验证，不模拟安全许可。
需要改变内存读取行为时修改；正式现场仍使用 S7Client。
"""


class OfflineReadClient:
    """明确标记为合成数据的内存只读客户端。"""
    source = 'offline_fixture'

    def __init__(self, buffers: dict[int, bytes]):
        """复制测试数据，不打开任何网络连接。"""
        self.buffers = {db: bytes(data) for db, data in buffers.items()}

    def read_bytes(self, db: int, byte_offset: int, size: int) -> bytes:
        """按请求切片并严格检查长度，错误时不补零。"""
        if any(type(v) is not int or v < 0 for v in (db, byte_offset, size)) or size == 0:
            raise ValueError('非法离线读取窗口')
        data = self.buffers[db][byte_offset:byte_offset + size]
        if len(data) != size:
            raise IOError('离线缓冲区长度不足')
        return data
