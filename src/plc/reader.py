"""
按业务名称读取 PLC；输入客户端与变量表，输出数值或 ShovelState。
所有地址由 variable_map 提供，未知地址不发起 I/O。
扩展业务读取接口时修改此文件，并先获得对应变量的可信映射。
"""
from plc.decoder import decode, SIZES
from plc.variable_map import require_address, max_required_end_offset
from models.shovel_state import ShovelState


class PLCReader:
    """顺序读取接口，不通过字段位置猜测地址。"""

    def __init__(self, client, mapping: dict):
        """接收客户端与集中变量表，构造时不联网。"""
        self.client = client
        self.mapping = mapping

    def read_variable(self, name: str) -> bool | int | float:
        """读取已确认具名变量；缺地址时说明所缺元数据并拒绝。"""
        entry = self.mapping[name]
        if entry['direction'] != 'read':
            raise ValueError('不能把写命令当作反馈读取')
        require_address(entry)
        data = self.client.read_bytes(entry['db'], entry['byte_offset'], SIZES[entry['data_type']])
        return decode(data, entry['data_type'], bit_offset=entry['bit_offset'])

    def read_control_mode(self) -> dict:
        """读取本地、远程、挖掘、行走模式；缺映射则拒绝，不假设远程。"""
        return {name: self.read_variable(name) for name in ('local_mode', 'remote_mode', 'dig_mode', 'propel_mode')}

    def read_fault_status(self) -> bool:
        """读取电铲故障指示；未知不能转换成 False。"""
        return self.read_variable('fault')

    def read_all_state(self) -> ShovelState:
        """按有效配置算窗口，逐 DB 一次读取；未知留空，短读/网络异常立即上抛。"""
        state = ShovelState(source=getattr(self.client, 'source', 'plc'))
        buffers = {}
        for name, entry in self.mapping.items():
            if entry['direction'] != 'read':
                continue
            try:
                require_address(entry)
            except NotImplementedError as error:
                state.errors[name] = str(error)
                continue
            db = entry['db']
            if db not in buffers:
                size = max_required_end_offset(self.mapping, db)
                buffers[db] = self.client.read_bytes(db, 0, size)
                if len(buffers[db]) != size:
                    raise IOError(f'PLC 批量短读：要求 {size} 字节，实际 {len(buffers[db])}')
            value = decode(buffers[db], entry['data_type'], entry['byte_offset'], entry['bit_offset'])
            if hasattr(state, name):
                setattr(state, name, value)
            else:
                state.additional_values[name] = value  # 其余电压/功率/行走及备用项仍保留
        state.control_mode = f'local={state.local_mode},remote={state.remote_mode},dig={state.dig_mode},propel={state.propel_mode}'
        state.limit_status = f'lift={state.lift_limit_triggered},push={state.push_limit_triggered}'
        return state

    def read_bucket_tilt_angle(self) -> float:
        """读取斗杆倾角 REAL；按 Excel 原注释保留符号，不擅自换算单位。"""
        return self.read_variable('bucket_tilt_angle')

    def read_lift_encoder(self) -> float:
        """读取提升编码器，来源 Siemens PLC/LIFT_ENCODER。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('lift_encoder')

    def read_push_encoder(self) -> float:
        """读取推压编码器，来源 Siemens PLC/PUSH_ENCODER。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('push_encoder')

    def read_swing_angle(self) -> float:
        """读取回转角度，来源 Siemens PLC/ROTATION_ANGLE。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('swing_angle')

    def read_lift_actual_speed(self) -> float:
        """读取提升电机实际转速，来源 Siemens PLC/LIFT_MOTOR_ACTUAL_SPEED。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('lift_actual_speed')

    def read_lift_current(self) -> float:
        """读取提升电机电流，来源 Siemens PLC/LIFT_MOTOR_CURRENT。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('lift_current')

    def read_lift_torque(self) -> float:
        """读取提升电机转矩，来源 Siemens PLC/LIFT_MOTOR_TORQUE。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('lift_torque')

    def read_push_actual_speed(self) -> float:
        """读取推压电机实际转速，来源 Siemens PLC/PUSH_MOTOR_ACTUAL_SPEED。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('push_actual_speed')

    def read_push_current(self) -> float:
        """读取推压电机电流，来源 Siemens PLC/PUSH_MOTOR_CURRENT。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('push_current')

    def read_push_torque(self) -> float:
        """读取推压电机转矩，来源 Siemens PLC/PUSH_MOTOR_TORQUE。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('push_torque')

    def read_swing_actual_speed(self) -> float:
        """读取回转电机实际转速，来源 Siemens PLC/ROTATION_MOTOR_ACTUAL_SPEED。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('swing_actual_speed')

    def read_swing_current(self) -> float:
        """读取回转电机电流，来源 Siemens PLC/ROTATION_MOTOR_CURRENT。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('swing_current')

    def read_swing_torque(self) -> float:
        """读取回转电机转矩，来源 Siemens PLC/ROTATION_MOTOR_TORQUE。

        返回原始 float；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('swing_torque')

    def read_lift_limit_triggered(self) -> bool:
        """读取提升限位触发，来源 Siemens PLC/LIFT_LIMIT_TRIGGERED。

        返回原始 bool；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('lift_limit_triggered')

    def read_push_limit_triggered(self) -> bool:
        """读取推压限位触发，来源 Siemens PLC/PUSH_LIMIT_TRIGGERED。

        返回原始 bool；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('push_limit_triggered')

    def read_lift_right_exec_result(self) -> bool:
        """读取提升/右行走执行结果，来源 Siemens PLC/LIFT_RIGHT_EXEC_RESULT。

        返回原始 bool；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('lift_right_exec_result')

    def read_push_left_exec_result(self) -> bool:
        """读取推压/左行走执行结果，来源 Siemens PLC/PUSH_LEFT_EXEC_RESULT。

        返回原始 bool；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('push_left_exec_result')

    def read_rotation_exec_result(self) -> bool:
        """读取回转执行结果，来源 Siemens PLC/ROTATION_EXEC_RESULT。

        返回原始 bool；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('rotation_exec_result')

    def read_lift_right_release_indicator(self) -> bool:
        """读取提升/右行走松闸指示灯，来源 Siemens PLC/LIFT_RIGHT_RELEASE_INDICATOR。

        返回原始 bool；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('lift_right_release_indicator')

    def read_push_left_release_indicator(self) -> bool:
        """读取推压/左行走松闸指示灯，来源 Siemens PLC/PUSH_LEFT_RELEASE_INDICATOR。

        返回原始 bool；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('push_left_release_indicator')

    def read_rotation_release_indicator(self) -> bool:
        """读取回转松闸指示灯，来源 Siemens PLC/ROTATION_RELEASE_INDICATOR。

        返回原始 bool；地址未确认抛 NotImplementedError，单位和换算尚需核实。
        """
        return self.read_variable('rotation_release_indicator')


FIELD_NAMES = ('lift_encoder', 'push_encoder', 'swing_angle', 'lift_actual_speed', 'lift_current', 'lift_torque', 'push_actual_speed', 'push_current', 'push_torque', 'swing_actual_speed', 'swing_current', 'swing_torque', 'local_mode', 'remote_mode', 'dig_mode', 'propel_mode', 'fault', 'lift_limit_triggered', 'push_limit_triggered', 'lift_right_exec_result', 'push_left_exec_result', 'rotation_exec_result', 'lift_right_release_indicator', 'push_left_release_indicator', 'rotation_release_indicator')
