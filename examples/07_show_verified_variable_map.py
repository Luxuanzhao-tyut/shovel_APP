"""
展示有来源的核心DB映射及三个警告；输入YAML，输出可核查清单。
“有来源”不等于现场验证，本示例不创建PLC客户端；增加关注变量时修改列表。
"""
import json
from _common import prepare
from plc.variable_map import load_variable_map


def main() -> int:
    """打印来源、偏移、备注、现场状态，最后明确IP冲突/非法位/禁写。"""
    _, config, logger = prepare('只展示映射，不连接PLC')
    mapping = load_variable_map()
    names = ['lift_encoder', 'push_encoder', 'swing_angle', 'bucket_tilt_angle',
             'lift_actual_speed', 'push_actual_speed', 'swing_actual_speed',
             'lift_right_target_position', 'push_left_target_position', 'rotation_target_position',
             'lift_right_set_speed', 'push_left_set_speed', 'rotation_set_speed']
    fields = ['display_name', 'db', 'data_type', 'byte_offset', 'bit_offset', 'direction',
              'source_type', 'confidence', 'verification_status', 'note', 'source']
    for name in names:
        logger.info('%s %s', name, json.dumps({key: mapping[name][key] for key in fields}, ensure_ascii=False))
    notes = config['source_notes']
    logger.warning('WARNING 1：PLC IP conflict；Java=%s；Excel=%s；status=%s',
                   notes['java_source_ip'], notes['excel_source_ip'], notes['ip_status'])
    for entry in mapping.values():
        if entry['confidence'] == 'INVALID_IN_SOURCE':
            logger.warning('WARNING 2：Invalid DB%s BOOL bit offset: %s；%s，未自动修正',
                           entry['db'], entry['raw_source_address'], entry['source_name'])
    logger.warning('WARNING 3：Real PLC write remains disabled.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
