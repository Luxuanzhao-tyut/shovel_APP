"""
定义规划层命令；输入目标与速度限制，输出具名数据对象。
该对象本身不向 PLC 发命令，单位未核实之前不得作为现场控制量。
以后增加已确认的规划命令字段时修改此文件。
"""
from dataclasses import dataclass


@dataclass
class ShovelCommand:
    """位置接口验证用命令；speed_limit 不等同于 Java 速度设定的已验证语义。"""
    lift_target: float | None = None  # 提升目标，原始单位待确认
    push_target: float | None = None  # 推压目标，原始单位待确认
    swing_target: float | None = None  # 回转目标，角度定义待核验
    lift_speed_limit: float | None = None  # 提升速度上限，PLC 对应能力待确认
    push_speed_limit: float | None = None  # 推压速度上限，PLC 对应能力待确认
    swing_speed_limit: float | None = None  # 回转速度上限，PLC 对应能力待确认
    stop: bool = False  # 停止请求，不代表硬件急停
