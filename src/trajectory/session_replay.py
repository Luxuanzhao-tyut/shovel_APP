from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


TRUE_VALUES = {'1', 'true', 'yes', 'y', '是', 'True', 'TRUE'}


def _bool(v: str | None) -> bool | None:
    if v is None or str(v).strip() == '':
        return None
    return str(v).strip() in TRUE_VALUES


def _float(v: str | None) -> float | None:
    if v is None or str(v).strip() == '':
        return None
    try:
        return float(v)
    except Exception:
        return None


def _seconds(ts: str | None) -> float | None:
    if not ts:
        return None
    text = ts.strip().replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


@dataclass(frozen=True)
class ReplayPoint:
    t_s: float
    mode: str  # dig | walk
    a_speed: float
    a_direction: str
    b_speed: float
    b_direction: str
    c_speed: float = 0.0
    c_direction: str = 'stop'


@dataclass(frozen=True)
class ReplaySession:
    path: Path
    mode: str
    points: tuple[ReplayPoint, ...]
    duration_s: float
    source_rows: int


def load_session(path: Path, fallback_period_s: float = 0.1) -> ReplaySession:
    """从本程序导出的 DB400 CSV 构造速度序列复现数据。

    方向使用电机实际转速符号，幅值优先使用 PLC 设定转速；这是旧 Java TrajectoryExecutor
    “记录人工操作后按速度序列复现”的同类思路。该过程仍属于开环速度复现，不是位置闭环。
    """
    path = Path(path)
    with path.open('r', newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError('CSV 中没有数据')

    dig_count = sum(_bool(r.get('dig_mode')) is True for r in rows)
    walk_count = sum(_bool(r.get('propel_mode')) is True for r in rows)
    if dig_count and walk_count:
        # 允许少量模式切换瞬间重叠/抖动，但不允许真正混合轨迹自动复现。
        dominant = max(dig_count, walk_count)
        other = min(dig_count, walk_count)
        if other > max(3, int(0.05 * dominant)):
            raise ValueError('该记录包含明显的挖掘/行走混合模式；请分别记录后再复现')
    mode = 'walk' if walk_count > dig_count else 'dig'

    first_ts = next((_seconds(r.get('timestamp')) for r in rows if _seconds(r.get('timestamp')) is not None), None)
    points: list[ReplayPoint] = []
    for i, r in enumerate(rows):
        ts = _seconds(r.get('timestamp'))
        t_s = (ts - first_ts) if (ts is not None and first_ts is not None) else i * fallback_period_s
        if mode == 'walk':
            left_actual = _float(r.get('left_walk_motor_actual_speed')) or 0.0
            right_actual = _float(r.get('right_walk_motor_actual_speed')) or 0.0
            left_set = _float(r.get('left_walk_motor_set_speed'))
            right_set = _float(r.get('right_walk_motor_set_speed'))
            left_mag = abs(left_set if left_set is not None else left_actual)
            right_mag = abs(right_set if right_set is not None else right_actual)
            left_dir = 'forward' if left_actual > 0 else 'backward' if left_actual < 0 else 'stop'
            right_dir = 'forward' if right_actual > 0 else 'backward' if right_actual < 0 else 'stop'
            points.append(ReplayPoint(t_s, 'walk', left_mag, left_dir, right_mag, right_dir))
        else:
            lift_actual = _float(r.get('lift_actual_speed')) or 0.0
            push_actual = _float(r.get('push_actual_speed')) or 0.0
            swing_actual = _float(r.get('swing_actual_speed')) or 0.0
            lift_set = _float(r.get('lift_motor_set_speed'))
            push_set = _float(r.get('push_motor_set_speed'))
            swing_set = _float(r.get('rotation_motor_set_speed'))
            lift_mag = abs(lift_set if lift_set is not None else lift_actual)
            push_mag = abs(push_set if push_set is not None else push_actual)
            swing_mag = abs(swing_set if swing_set is not None else swing_actual)
            # 与旧 Java TrajectoryExecutor 的符号语义一致。
            lift_dir = 'up' if lift_actual < 0 else 'down' if lift_actual > 0 else 'stop'
            push_dir = 'forward' if push_actual > 0 else 'backward' if push_actual < 0 else 'stop'
            swing_dir = 'left' if swing_actual > 0 else 'right' if swing_actual < 0 else 'stop'
            points.append(ReplayPoint(t_s, 'dig', lift_mag, lift_dir, push_mag, push_dir, swing_mag, swing_dir))

    if not points:
        raise ValueError('没有可复现的数据点')
    duration = max(0.0, points[-1].t_s - points[0].t_s)
    return ReplaySession(path, mode, tuple(points), duration, len(rows))
