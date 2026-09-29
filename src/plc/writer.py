"""DB401 写计划预览。

真实写入由 plc.live_control.LiveControlManager 统一执行；本类保留原有 preview API，
方便 UI 在未武装状态下展示写入地址和值，避免预演和真写逻辑混在一起。
"""
from plc.decoder import encode
from plc.variable_map import require_address


class PLCWriter:
    def __init__(self, client, config: dict, mapping: dict):
        self.client = client
        self.config = config
        self.mapping = mapping

    def preview(self, name: str, value: bool | float) -> dict:
        entry = self.mapping[name]
        if entry['direction'] != 'write':
            raise ValueError('不能向反馈变量生成写计划')
        if entry['data_type'] == 'BOOL':
            if type(value) is not bool:
                raise ValueError('BOOL 命令需要布尔值')
        else:
            encode(value, entry['data_type'])
        address_known = True
        try:
            require_address(entry)
        except NotImplementedError:
            address_known = False
        payload = None if entry['data_type'] == 'BOOL' else encode(value, entry['data_type']).hex()
        return {
            'kind': 'DRY_RUN_PLAN_ONLY', 'written': False, 'name': name,
            'display_name': entry['display_name'], 'value': value,
            'db': entry['db'], 'byte_offset': entry['byte_offset'], 'bit_offset': entry['bit_offset'],
            'payload_hex': payload, 'address_known': address_known,
            'raw_source_address': entry.get('raw_source_address'),
            'source_type': entry.get('source_type'), 'source': entry.get('source'),
            'confidence': entry.get('confidence'), 'verification_status': entry.get('verification_status'),
            'note': entry.get('note'),
            'message': f"未武装时仅预演：{entry['display_name']}={value}",
        }

    def stop_motion(self) -> list[dict]:
        values = {
            'lift_right_set_speed': 0.0, 'push_left_set_speed': 0.0, 'rotation_set_speed': 0.0,
            'lift_up_or_right_forward': False, 'lift_down_or_right_backward': False,
            'push_forward_or_left_forward': False, 'push_backward_or_left_backward': False,
            'rotation_left': False, 'rotation_right': False,
        }
        return [self.preview(name, value) for name, value in values.items()]
