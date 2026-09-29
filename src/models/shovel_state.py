"""
统一电铲状态：输入已解码的 PLC 反馈，输出供记录和算法使用的具名字段。
None 表示未知，不是零或无故障；编码器保留原始数值，不假设长度单位。
增加可核实的反馈字段时修改此文件。
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ShovelState:
    """一次采集结果；多变量顺序读取不保证 PLC 同一扫描周期。"""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())  # UTC 采集开始时间
    source: str = 'plc'  # plc 或 offline_empty，避免演示数据误认为实测
    control_mode: str = 'UNKNOWN'  # 本地/远程及作业模式的可读摘要
    limit_status: str = 'UNKNOWN'  # 已确认的提升/推压限位摘要，不代表整机限位
    errors: dict[str, str] = field(default_factory=dict)  # 缺地址或读取失败原因
    additional_values: dict[str, bool | int | float] = field(default_factory=dict)  # 其余电压/功率/行走/备用反馈
    bucket_tilt_angle: float | None = None  # 斗杆倾角；原表水平为0°，向下正，向上负
    communication_ok: bool | None = None  # 通讯正常反馈；具体监测逻辑尚未核验
    high_voltage_indicator: bool | None = None  # 高压运行反馈
    rectifier_indicator: bool | None = None  # 整流运行反馈
    auto_unmanned_mode: bool | None = None  # 无人自动模式反馈
    jog_unmanned_mode: bool | None = None  # 无人点动模式反馈
    lift_encoder: float | None = None  # 提升编码器；未知保留 None
    push_encoder: float | None = None  # 推压编码器；未知保留 None
    swing_angle: float | None = None  # 回转角度；未知保留 None
    lift_actual_speed: float | None = None  # 提升电机实际转速；未知保留 None
    lift_current: float | None = None  # 提升电机电流；未知保留 None
    lift_torque: float | None = None  # 提升电机转矩；未知保留 None
    push_actual_speed: float | None = None  # 推压电机实际转速；未知保留 None
    push_current: float | None = None  # 推压电机电流；未知保留 None
    push_torque: float | None = None  # 推压电机转矩；未知保留 None
    swing_actual_speed: float | None = None  # 回转电机实际转速；未知保留 None
    swing_current: float | None = None  # 回转电机电流；未知保留 None
    swing_torque: float | None = None  # 回转电机转矩；未知保留 None
    local_mode: bool | None = None  # 本地控制模式；未知保留 None
    remote_mode: bool | None = None  # 远程控制模式；未知保留 None
    dig_mode: bool | None = None  # 挖掘模式指示灯；未知保留 None
    propel_mode: bool | None = None  # 行走模式指示灯；未知保留 None
    fault: bool | None = None  # 电铲故障指示灯；未知保留 None
    lift_limit_triggered: bool | None = None  # 提升限位触发；未知保留 None
    push_limit_triggered: bool | None = None  # 推压限位触发；未知保留 None
    lift_right_exec_result: bool | None = None  # 提升/右行走执行结果；未知保留 None
    push_left_exec_result: bool | None = None  # 推压/左行走执行结果；未知保留 None
    rotation_exec_result: bool | None = None  # 回转执行结果；未知保留 None
    lift_right_release_indicator: bool | None = None  # 提升/右行走松闸指示灯；未知保留 None
    push_left_release_indicator: bool | None = None  # 推压/左行走松闸指示灯；未知保留 None
    rotation_release_indicator: bool | None = None  # 回转松闸指示灯；未知保留 None
