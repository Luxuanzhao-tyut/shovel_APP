"""离线验证 Siemens 编解码；输入固定测试向量，输出 pytest 断言；不连接 PLC，新增类型时扩展。"""
import pytest
from plc.decoder import decode, encode


@pytest.mark.parametrize('kind,raw,value', [
    ('REAL', bytes.fromhex('3f800000'), 1.0), ('REAL', bytes.fromhex('c0200000'), -2.5),
    ('INT', bytes.fromhex('8000'), -32768), ('INT', bytes.fromhex('7fff'), 32767),
    ('WORD', bytes.fromhex('ffff'), 65535), ('DINT', bytes.fromhex('80000000'), -2147483648),
    ('BYTE', bytes.fromhex('ff'), 255),
])
def test_known_vectors(kind, raw, value):
    """用固定大端向量验证解码和编码，不只进行自洽的往返测试。"""
    assert decode(raw, kind) == value
    assert encode(value, kind) == raw


@pytest.mark.parametrize('bit', range(8))
def test_boolean_bits(bit):
    """验证全部位号和对其他位的保留。"""
    assert decode(bytes([1 << bit]), 'BOOL', bit_offset=bit) is True
    assert decode(bytes([255 ^ (1 << bit)]), 'BOOL', bit_offset=bit) is False
    assert encode(False, 'BOOL', bit, 255) == bytes([255 ^ (1 << bit)])
    assert encode(True, 'BOOL', bit, 0) == bytes([1 << bit])


@pytest.mark.parametrize('value,kind', [(float('nan'), 'REAL'), (float('inf'), 'REAL'), (1e100, 'REAL'), (32768, 'INT'), (1.1, 'INT'), (True, 'INT')])
def test_invalid_values(value, kind):
    """拒绝非有限数、错误类型与溢出。"""
    with pytest.raises(ValueError):
        encode(value, kind)


def test_short_and_offsets():
    """禁止重现 Java 的末尾补零；验证相对偏移与非法 bit。"""
    with pytest.raises(ValueError):
        decode(b'\0\0\0', 'REAL')
    assert decode(bytes.fromhex('003f800000'), 'REAL', 1) == 1.0
    with pytest.raises(ValueError):
        decode(b'\0', 'BOOL', bit_offset=8)
