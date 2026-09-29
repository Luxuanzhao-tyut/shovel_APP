"""
将 S7 原始字节与 Python 数值互转；输入字节/数值，输出数值/字节。
多字节整数采用大端，REAL 为 IEEE754 大端 float32；BOOL 位 0 是最低位。
byte_offset 在 reader 层决定，本模块 offset 是输入缓冲区内的相对偏移。
扩展数据类型时修改此文件，不涉及现场地址。
"""
import math
import struct

FORMATS = {'BYTE': '>B', 'WORD': '>H', 'INT': '>h', 'DINT': '>i', 'REAL': '>f'}
SIZES = {'BOOL': 1, 'BYTE': 1, 'WORD': 2, 'INT': 2, 'DINT': 4, 'REAL': 4}


def decode(data: bytes, data_type: str, offset: int = 0, bit_offset: int | None = None) -> bool | int | float:
    """严格解码完整字节；短读即报错，绝不补零伪造 PLC 反馈。"""
    if data_type not in SIZES:
        raise ValueError(f'不支持的数据类型 {data_type}')
    if type(offset) is not int or offset < 0 or len(data) < offset + SIZES[data_type]:
        raise ValueError('字节长度不足或相对偏移非法')
    if data_type == 'BOOL':
        if type(bit_offset) is not int or not 0 <= bit_offset <= 7:
            raise ValueError('BOOL bit_offset 必须为 0..7')
        return bool(data[offset] & (1 << bit_offset))
    if bit_offset is not None:
        raise ValueError('非 BOOL 不接受 bit_offset')
    return struct.unpack_from(FORMATS[data_type], data, offset)[0]


def encode(value: bool | int | float, data_type: str, bit_offset: int | None = None, original_byte: int = 0) -> bytes:
    """编码数值；BOOL 保留原字节其他位，此功能本身不等于原子 PLC 位写。"""
    if data_type == 'BOOL':
        if type(value) is not bool or type(bit_offset) is not int or not 0 <= bit_offset <= 7:
            raise ValueError('BOOL 要求布尔值及 0..7 位号')
        if type(original_byte) is not int or not 0 <= original_byte <= 255:
            raise ValueError('原字节须为 0..255 整数')
        mask = 1 << bit_offset
        return bytes([(original_byte | mask) if value else (original_byte & ~mask)])
    if data_type not in FORMATS or bit_offset is not None:
        raise ValueError('数据类型或 bit_offset 非法')
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('数值必须有限，不能为布尔、NaN 或无穷大')
    if data_type != 'REAL' and type(value) is not int:
        raise ValueError('整数 PLC 类型要求 Python int')
    try:
        return struct.pack(FORMATS[data_type], value)
    except (struct.error, OverflowError) as error:
        raise ValueError('数值超出 PLC 类型范围') from error
