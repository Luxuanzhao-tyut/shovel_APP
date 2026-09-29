"""
该算法属于速度序列开环复现，并非闭环轨迹跟踪，不建议作为最终自主控制方案。
输入显式历史速度点和配置，输出按固定间隔排列的离线写计划；不持有 PLC 连接。
保留 Java 挖掘路径的符号和回转换算供对照，不执行模式切换、松闸或真实回放。
研究 baseline 或获得速度标定证据后修改本文件。
"""
import math
from trajectory.trajectory_point import TrajectoryPoint


def build_replay_plan(points: list[TrajectoryPoint], config: dict) -> list[dict]:
    """建立逻辑时间表，不 sleep、不调用 writer；先验证全部输入避免部分计划混入错误。"""
    legacy = config['legacy']
    period = legacy['replay_period_ms']
    divisor = legacy['swing_speed_divisor']
    sign = legacy['swing_speed_sign']
    for value in (period, divisor, sign):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('历史参数须为有限数值')
    if period <= 0 or divisor <= 0 or sign not in (-1, 1):
        raise ValueError('历史周期/换算配置非法')
    result = []
    for index, point in enumerate(points):
        row = {'time_ms': index * period, 'kind': 'OFFLINE_OPEN_LOOP_PLAN'}
        for axis in ('lift', 'push', 'swing'):
            speed = getattr(point, f'{axis}_speed')
            if speed is None:
                continue
            if type(speed) not in (float, int) or not math.isfinite(speed):
                raise ValueError('轨迹速度须为有限数值')
            positive, negative = {'lift': ('down', 'up'), 'push': ('forward', 'backward'), 'swing': ('left', 'right')}[axis]
            row[f'{axis}_direction'] = positive if speed > 0 else negative if speed < 0 else 'stop'
            row[f'{axis}_speed'] = speed * sign / divisor if axis == 'swing' else speed
        result.append(row)
    return result
