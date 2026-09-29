"""
描述旧速度回放的一帧；输入显式速度，输出轨迹点数据对象。
这里只保存原始历史速度，不含 PLC 地址，不表示闭环轨迹。
新增已核实的历史字段时修改此文件。
"""
from dataclasses import dataclass


@dataclass
class TrajectoryPoint:
    """None 表示该轴本帧没有命令；0 表示计划停该轴。"""
    lift_speed: float | None = None  # 历史提升实际速度，原始单位
    push_speed: float | None = None  # 历史推压实际速度，原始单位
    swing_speed: float | None = None  # 历史回转实际速度，原始单位
