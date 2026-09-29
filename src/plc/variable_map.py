"""
集中加载变量映射，输入 YAML，输出具名变量记录。
未知地址保持 null，任何读取前都必须调用 require_address。
获得可信元数据后修改 YAML；变更合法性规则时修改本文件。
"""
from pathlib import Path
import re
import yaml
from plc.config import PROJECT_ROOT
from plc.decoder import SIZES

SOURCE_TYPES = {'JAVA_SOURCE', 'JAVA_MYSQL_POINT_TABLE', 'TIA_GLOBAL_TAG_TABLE', 'TIA_DB_SCREENSHOT', 'LADDER_SCREENSHOT', 'INFERENCE'}
CONFIDENCES = {'VERIFIED_FROM_SOURCE', 'CONFIRMED_FROM_EXCEL', 'PARTIALLY_CONFIRMED',
               'POSSIBLE_CANDIDATE', 'SOURCE_CONFLICT', 'SOURCE_CONFLICT_OR_INVALID',
               'INVALID_IN_SOURCE', 'UNKNOWN', 'UNKNOWN_FROM_DATABASE'}
ADDRESS_CONFIDENCES = {'CONFIRMED_FROM_EXCEL', 'VERIFIED_FROM_SOURCE'}
FORMAL_SOURCE_TYPES = {'JAVA_SOURCE', 'JAVA_MYSQL_POINT_TABLE', 'TIA_DB_SCREENSHOT'}


def parse_point_address(data_type: str, raw_address: str) -> tuple[int, int | None]:
    """严格解析点表地址；BOOL 位号只允许 0~7。历史源表中的 2.8 仍会被拒绝。"""
    raw = str(raw_address).strip()
    if data_type == 'BOOL':
        if not re.fullmatch(r'\d+\.[0-7]', raw):
            raise ValueError(f'非法 BOOL 来源地址：{raw}')
        byte, bit = raw.split('.')
        return int(byte), int(bit)
    if data_type not in SIZES or not re.fullmatch(r'\d+', raw):
        raise ValueError(f'非法来源类型或字节地址：{data_type}/{raw}')
    return int(raw), None


def load_variable_map(path: Path | None = None) -> dict:
    """读取并校验变量表；校验结构合法不意味着地址已确认。"""
    with (path or PROJECT_ROOT / 'config/variable_map.yaml').open(encoding='utf-8-sig') as stream:
        mapping = yaml.safe_load(stream)
    validate_map(mapping)
    return mapping


def validate_map(mapping: dict) -> None:
    """检查类型、偏移、方向、证据与重叠，避免错误配置进入读取层。"""
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError('变量表必须是非空字典')
    occupied = set()
    for name, entry in mapping.items():
        if entry['direction'] not in ('read', 'write'):
            raise ValueError(f'{name}: 非法方向')
        if entry['data_type'] not in (*SIZES, None):
            raise ValueError(f'{name}: 非法数据类型')
        if entry['confidence'] not in CONFIDENCES:
            raise ValueError(f'{name}: 非法确认级别')
        if entry.get('source_type') not in SOURCE_TYPES:
            raise ValueError(f'{name}: 非法数据来源层级')
        if entry.get('verification_status') not in ('NOT_TESTED_ON_PLC', 'VERIFIED_ON_PLC'):
            raise ValueError(f'{name}: 缺少现场验证状态')
        if type(entry.get('valid_address')) is not bool:
            raise ValueError(f'{name}: valid_address 必须为布尔值')
        for key in ('db', 'byte_offset'):
            value = entry[key]
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f'{name}: {key} 须为非负整数或 null')
        bit = entry['bit_offset']
        if bit is not None and (type(bit) is not int or not 0 <= bit <= 7):
            raise ValueError(f'{name}: 非法位号')
        if entry['data_type'] != 'BOOL' and bit is not None:
            raise ValueError(f'{name}: 非 BOOL 不应有位号')
        if not entry['valid_address']:
            if entry['byte_offset'] is not None or bit is not None:
                raise ValueError(f'{name}: 隔离项只能保存 raw_source_address，不能保留有效偏移')
        else:
            if not entry.get('source'):
                raise ValueError(f'{name}: 缺少证据来源')
            require_address(entry)
            if 'raw_source_address' in entry:
                if parse_point_address(entry['data_type'], entry['raw_source_address']) != (entry['byte_offset'], bit):
                    raise ValueError(f'{name}: 来源地址与正式偏移不一致')
            start = entry['byte_offset'] * 8
            bits = [start + bit] if entry['data_type'] == 'BOOL' else range(start, start + SIZES[entry['data_type']] * 8)
            for position in bits:
                address = (entry['db'], position)
                if address in occupied:
                    raise ValueError(f'{name}: 已确认地址重叠')
                occupied.add(address)


def require_address(entry: dict) -> None:
    """只有正式通信层且有可靠来源的地址可使用；现场未验证不等于地址缺失。"""
    complete = all(type(entry.get(key)) is int and entry[key] >= 0 for key in ('db', 'byte_offset'))
    complete = complete and entry.get('data_type') in SIZES
    bit = entry.get('bit_offset')
    complete = complete and ((type(bit) is int and 0 <= bit <= 7) if entry.get('data_type') == 'BOOL' else bit is None)
    if (entry.get('valid_address') is not True or entry.get('confidence') not in ADDRESS_CONFIDENCES
            or entry.get('source_type') not in FORMAL_SOURCE_TYPES or not complete
            or not entry.get('source') or entry.get('verification_status') not in ('NOT_TESTED_ON_PLC', 'VERIFIED_ON_PLC')):
        raise NotImplementedError(f"{entry.get('display_name')}: {entry.get('confidence', 'UNKNOWN')}；地址未批准用于正式 DB 接口，请核查来源/冲突/隔离状态")


def max_required_end_offset(mapping: dict, db: int) -> int:
    """根据有效读取项自动计算末端独占偏移，防止最后一个 REAL 被截断。"""
    ends = []
    for entry in mapping.values():
        if entry['db'] == db and entry['direction'] == 'read' and entry.get('valid_address') is True:
            require_address(entry)
            ends.append(entry['byte_offset'] + SIZES[entry['data_type']])
    if not ends:
        raise NotImplementedError('此 DB 无可靠读取地址')
    return max(ends)
