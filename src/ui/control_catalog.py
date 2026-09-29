from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    label: str
    group: str
    value_type: str = "bool"  # bool | float
    momentary: bool = False
    mode: str | None = None  # dig | walk | any
    note: str = ""


# 非备用功能点。地址是否可用由 config/variable_map.yaml 决定，不在 UI 中猜测。
COMMANDS = [
    CommandSpec("local_mode_button", "本地模式", "模式", momentary=False, note="Java ButtonServiceImpl 采用本地/远程保持型互斥位"),
    CommandSpec("remote_mode_button", "远程模式", "模式", momentary=False, note="Java ButtonServiceImpl 采用本地/远程保持型互斥位"),
    CommandSpec("auto_unmanned_mode_button", "无人自动模式", "模式", momentary=True),
    CommandSpec("jog_unmanned_mode_button", "无人点动模式", "模式", momentary=True),
    CommandSpec("communication_heartbeat", "通信心跳", "系统", momentary=False, note="LiveControlManager 武装后自动以 10 Hz 翻转，不提供手动按钮"),
    CommandSpec("high_voltage_start", "高压启动", "电源", momentary=True),
    CommandSpec("high_voltage_stop", "高压停止", "电源", momentary=True),
    CommandSpec("rectifier_start", "整流启动", "电源", momentary=True),
    CommandSpec("rectifier_stop", "整流停止", "电源", momentary=True),
    CommandSpec("emergency_stop_button", "软件急停请求", "安全", momentary=True,
                note="不等同于独立硬件急停，不可替代现场急停回路"),
    CommandSpec("fault_reset_button", "复位", "安全", momentary=True),
    CommandSpec("dig_mode_button", "挖掘模式", "模式", momentary=True),
    CommandSpec("walk_mode_button", "行走模式", "模式", momentary=True),
    CommandSpec("lift_right_release_brake_open", "提升/右履带松闸", "制动", momentary=True),
    CommandSpec("lift_right_release_brake_close", "提升/右履带抱闸", "制动", momentary=True),
    CommandSpec("push_left_valve_open", "推压/左履带松闸", "制动", momentary=True),
    CommandSpec("push_left_valve_close", "推压/左履带抱闸", "制动", momentary=True),
    CommandSpec("rotation_brake_open", "回转松闸", "制动", momentary=True),
    CommandSpec("rotation_brake_close", "回转抱闸", "制动", momentary=True),
    CommandSpec("lift_up_or_right_forward", "提升向上 / 右履带向前", "方向", momentary=True),
    CommandSpec("lift_down_or_right_backward", "提升向下 / 右履带向后", "方向", momentary=True),
    CommandSpec("push_forward_or_left_forward", "推压向前 / 左履带向前", "方向", momentary=True),
    CommandSpec("push_backward_or_left_backward", "推压向后 / 左履带向后", "方向", momentary=True),
    CommandSpec("rotation_left", "回转向左", "方向", momentary=True, mode="dig"),
    CommandSpec("rotation_right", "回转向右", "方向", momentary=True, mode="dig",
                note="TIA Portal 已确认 DB401.DBX3.0；真机写入仍受全局安全锁限制"),
    CommandSpec("bucket_open_command", "开斗", "辅助", momentary=True, mode="dig",
                note="TIA Portal 已确认 DB401.DBX3.1；真机写入仍未开放"),
    CommandSpec("horn_command", "喇叭", "辅助", momentary=True,
                note="TIA Portal 已确认 DB401.DBX3.2；真机写入仍未开放"),
    CommandSpec("lift_right_target_position", "提升/右履带目标位置", "目标", "float"),
    CommandSpec("push_left_target_position", "推压/左履带目标位置", "目标", "float"),
    CommandSpec("rotation_target_position", "回转目标位置", "目标", "float", mode="dig"),
    CommandSpec("lift_right_set_speed", "提升/右履带设定转速", "速度", "float"),
    CommandSpec("push_left_set_speed", "推压/左履带设定转速", "速度", "float"),
    CommandSpec("rotation_set_speed", "回转设定转速", "速度", "float", mode="dig"),
    CommandSpec("lift_right_auto_start", "提升/右履带自动执行开始", "自动执行", momentary=True,
                note="保留接口；现场已禁用该 PLC 自动开始链，UI 改用上位机反馈闭环"),
    CommandSpec("push_left_auto_start", "推压/左履带自动执行开始", "自动执行", momentary=True,
                note="保留接口；现场已禁用该 PLC 自动开始链，UI 改用上位机反馈闭环"),
    CommandSpec("rotation_auto_start", "回转自动执行开始", "自动执行", momentary=True, mode="dig",
                note="保留接口；现场已禁用该 PLC 自动开始链，UI 改用上位机反馈闭环"),
]

COMMAND_BY_NAME = {item.name: item for item in COMMANDS}

DIG_DIRECTION = {
    "lift_up": "lift_up_or_right_forward",
    "lift_down": "lift_down_or_right_backward",
    "push_forward": "push_forward_or_left_forward",
    "push_backward": "push_backward_or_left_backward",
    "swing_left": "rotation_left",
    "swing_right": "rotation_right",
}

WALK_DIRECTION = {
    "right_forward": "lift_up_or_right_forward",
    "right_backward": "lift_down_or_right_backward",
    "left_forward": "push_forward_or_left_forward",
    "left_backward": "push_backward_or_left_backward",
}

SPEED_COMMANDS = {
    "lift": "lift_right_set_speed",
    "push": "push_left_set_speed",
    "swing": "rotation_set_speed",
    "right_track": "lift_right_set_speed",
    "left_track": "push_left_set_speed",
}

TARGET_COMMANDS = {
    "lift": "lift_right_target_position",
    "push": "push_left_target_position",
    "swing": "rotation_target_position",
}
