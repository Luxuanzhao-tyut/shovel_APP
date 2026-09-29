"""
离线检验Excel地址、来源隔离与具名读取；输入独立字节向量，输出pytest断言。
没有现场连接，测试中的地址期望来自已审阅单元格；映射或来源变更时扩展。
"""
from copy import deepcopy
import json
import yaml
import pytest
from plc.variable_map import load_variable_map, validate_map, require_address, parse_point_address, max_required_end_offset
from plc.config import load_config, PROJECT_ROOT
from plc.reader import PLCReader
from plc.offline_client import OfflineReadClient


def test_source_counts_and_statuses():
    """完整保留备用行及隔离行，不把有效地址计数当现场验证计数。"""
    mapping = load_variable_map()
    assert len(mapping) == 117
    reads = [e for e in mapping.values() if e['direction'] == 'read']
    writes = [e for e in mapping.values() if e['direction'] == 'write']
    assert len(reads) == 70 and sum(not e['reserved'] for e in reads) == 56
    assert len(writes) == 47 and sum(e['valid_address'] for e in writes) == 36
    assert all(e['verification_status'] == 'NOT_TESTED_ON_PLC' for e in mapping.values())
    assert {e['source_type'] for e in mapping.values()} == {'JAVA_MYSQL_POINT_TABLE', 'TIA_DB_SCREENSHOT'}


@pytest.mark.parametrize('key,value', [('byte_offset', -1), ('byte_offset', True), ('bit_offset', 8), ('data_type', 'FLOAT'), ('direction', 'both'), ('confidence', 'YES')])
def test_bad_mapping(key, value):
    """非法偏移或类型在配置加载阶段拒绝。"""
    mapping = load_variable_map()
    mapping['lift_encoder'][key] = value
    with pytest.raises(ValueError):
        validate_map(mapping)


@pytest.mark.parametrize('name,offset,raw,value,method', [
    ('lift_encoder', 142, '449a5000', 1234.5, 'read_lift_encoder'),
    ('push_encoder', 146, 'c1480000', -12.5, 'read_push_encoder'),
    ('swing_angle', 150, 'c1f00000', -30.0, 'read_swing_angle'),
    ('bucket_tilt_angle', 154, '40e80000', 7.25, 'read_bucket_tilt_angle'),
])
def test_named_real_path(name, offset, raw, value, method):
    """经正式reader从已知位置读独立向量，不只测试decoder自洽。"""
    mapping = load_variable_map()
    assert (mapping[name]['db'], mapping[name]['data_type'], mapping[name]['byte_offset']) == (400, 'REAL', offset)
    buffer = bytearray(158)
    buffer[offset:offset + 4] = bytes.fromhex(raw)
    reader = PLCReader(OfflineReadClient({400: buffer}), mapping)
    assert getattr(reader, method)() == value


def test_bulk_includes_last_real_and_feedback():
    """全部配置计算出158字节，单次读包含最后倾角与三轴速度。"""
    mapping = load_variable_map()
    assert max_required_end_offset(mapping, 400) == 158
    buffer = bytearray(158)
    for offset in (42, 66, 90, 142, 146, 150, 154):
        buffer[offset:offset + 4] = bytes.fromhex('41200000')
    buffer[0] = 0b00010010  # 测试远程/通信反馈，不代表现场联锁许可
    class CountingClient(OfflineReadClient):
        """记录bulk实际请求次数与长度。"""
        def read_bytes(self, db, byte_offset, size):
            """断言一次完整读取。"""
            self.calls.append((db, byte_offset, size))
            return super().read_bytes(db, byte_offset, size)
    client = CountingClient({400: buffer})
    client.calls = []
    state = PLCReader(client, mapping).read_all_state()
    assert client.calls == [(400, 0, 158)]
    assert state.bucket_tilt_angle == state.lift_actual_speed == state.push_actual_speed == state.swing_actual_speed == 10.0
    assert state.remote_mode is True and state.communication_ok is True
    assert state.source == 'offline_fixture'
    assert state.errors == {}
    assert 'right_walk_motor_current' in state.additional_values


def test_bulk_short_read_rejected():
    """即使测试客户端没有自己检查短读，reader也拒绝155字节窗口。"""
    class ShortClient:
        """返回Java旧长度的内存夹具。"""
        def read_bytes(self, *args):
            """固定返回短读数据。"""
            return bytes(155)
    with pytest.raises(IOError, match='短读'):
        PLCReader(ShortClient(), load_variable_map()).read_all_state()


@pytest.mark.parametrize('bit', range(8))
def test_legal_bit_parser(bit):
    """0至7均合法，不通过浮点加法处理位地址。"""
    assert parse_point_address('BOOL', f'2.{bit}') == (2, bit)


def test_historical_28_is_rejected_but_tia_resolves_current_db401():
    """历史 Excel 的 2.8 仍非法；当前正式映射采用 TIA Portal 直接确认的 3.0~3.5。"""
    with pytest.raises(ValueError, match='2.8'):
        parse_point_address('BOOL', '2.8')
    mapping = load_variable_map()
    expected = {
        'rotation_right': (3, 0),
        'bucket_open_command': (3, 1),
        'horn_command': (3, 2),
        'lift_right_auto_start': (3, 3),
        'push_left_auto_start': (3, 4),
        'rotation_auto_start': (3, 5),
    }
    for name, address in expected.items():
        entry = mapping[name]
        assert entry['source_type'] == 'TIA_DB_SCREENSHOT'
        assert entry['confidence'] == 'VERIFIED_FROM_SOURCE'
        assert entry['valid_address'] is True
        assert (entry['byte_offset'], entry['bit_offset']) == address
        require_address(entry)
    assert mapping['push_left_auto_start']['source_name'] == '推压/左行走自动执行开始'
    assert mapping['db401_reserved_3_5']['valid_address'] is False
    assert mapping['db401_reserved_3_5']['confidence'] == 'SOURCE_CONFLICT'


@pytest.mark.parametrize('source_type,confidence', [
    ('TIA_GLOBAL_TAG_TABLE', 'VERIFIED_FROM_SOURCE'), ('INFERENCE', 'POSSIBLE_CANDIDATE'),
    ('JAVA_MYSQL_POINT_TABLE', 'POSSIBLE_CANDIDATE'), ('JAVA_MYSQL_POINT_TABLE', 'SOURCE_CONFLICT'),
    ('JAVA_MYSQL_POINT_TABLE', 'UNKNOWN'), ('JAVA_MYSQL_POINT_TABLE', 'UNKNOWN_FROM_DATABASE'),
])
def test_unsafe_source_cannot_enter_reader(source_type, confidence):
    """即使伪装出完整数值偏移，非正式来源/候选/未知也不能走业务读取。"""
    mapping = load_variable_map()
    mapping['lift_encoder'].update(source_type=source_type, confidence=confidence)
    with pytest.raises(NotImplementedError):
        PLCReader(None, mapping).read_lift_encoder()


def test_tia_does_not_override_db_addresses():
    """同名DWORD I区与REAL DB区独立保留，正式reader不加载TIA文件。"""
    with (PROJECT_ROOT / 'config/tia_tag_map.yaml').open(encoding='utf-8') as stream:
        tags = yaml.safe_load(stream)['tags']
    lookup = {tag['name']: tag for tag in tags}
    assert lookup['提升编码器']['logical_address'] == '%ID46'
    assert lookup['推压编码器']['logical_address'] == '%ID62'
    mapping = load_variable_map()
    assert mapping['lift_encoder']['byte_offset'] == 142
    assert mapping['push_encoder']['byte_offset'] == 146
    assert lookup['Tag_90']['semantic_confidence'] == 'POSSIBLE_CANDIDATE'
    assert all('logical_address' not in entry for entry in mapping.values())


def test_ip_conflict_retained_and_not_silently_cleared(tmp_path):
    """两个原始IP均可查询；无人工说明不能把冲突标成已解决。"""
    config = load_config()
    notes = config['source_notes']
    assert notes['ip_status'] == 'SITE_CONFIRMED'
    assert notes['java_source_ip'] == '192.168.2.20'
    assert notes['excel_source_ip'] == '192.168.0.10'
    assert config['plc']['active_ip'] == notes['java_source_ip']
    # 回归检查：如果未来把现场确认标志清掉，就不能仅改状态字符串来静默消除历史来源冲突。
    notes['site_ip_confirmed'] = False
    notes['ip_status'] = 'RESOLVED'
    notes.pop('site_confirmation_note', None)
    path = tmp_path / 'bad.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    with pytest.raises(ValueError, match='UNRESOLVED_CONFLICT'):
        load_config(path)


def test_duplicate_evidence_and_source_trace():
    """一份点表加一份TIA为两个不同层级来源，父目录重复副本不增加证据。"""
    audit = json.loads((PROJECT_ROOT / 'data/excel_source_audit.json').read_text(encoding='utf-8'))
    assert len(audit['inventory']) == audit['unique_source_count'] == 2
    assert all(item['parent_copy_identical'] for item in audit['inventory'])
    assert len(audit['tia_tags']) == 363
    for entry in load_variable_map().values():
        source = entry['source']
        if entry['source_type'] == 'JAVA_MYSQL_POINT_TABLE':
            assert source['sha256'] and source['address_cell']
        elif entry['source_type'] == 'TIA_DB_SCREENSHOT':
            assert source['block'] == '接收_原始 [DB401]' and source['snapshot']
        else:
            raise AssertionError(entry['source_type'])


def test_overlap_and_raw_source_disagreement():
    """地址重叠与来源原文不一致均必须被发现。"""
    mapping = load_variable_map()
    mapping['duplicate'] = deepcopy(mapping['lift_encoder'])
    with pytest.raises(ValueError, match='重叠'):
        validate_map(mapping)
    mapping = load_variable_map()
    mapping['lift_encoder']['byte_offset'] = 140
    with pytest.raises(ValueError, match='来源地址'):
        validate_map(mapping)
