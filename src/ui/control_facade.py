from __future__ import annotations

import copy
import time
from dataclasses import asdict
from pathlib import Path

from plc.config import load_config
from plc.live_control import LiveControlManager
from plc.reader import PLCReader
from plc.s7_client import S7Client
from plc.variable_map import load_variable_map
from plc.writer import PLCWriter
from recording.csv_recorder import CSVRecorder
from recording.session_recorder import SessionRecorder


class ControlFacade:
    """UI 与 PLC 后端之间的统一入口。

    连接成功即启用真实写会话。
    LiveControlManager 仍根据 DB400 新鲜状态和联锁决定每条 DB401 命令是否允许执行。
    """

    def __init__(self) -> None:
        self.base_config = load_config()
        self.mapping = load_variable_map()
        self.config = copy.deepcopy(self.base_config)
        self.client = S7Client(self.config)
        self.reader = PLCReader(self.client, self.mapping)
        self.writer = PLCWriter(self.client, self.config, self.mapping)
        self.live = self._make_live()
        self.recorder: CSVRecorder | SessionRecorder | None = None
        self.auto_recorder: SessionRecorder | None = None
        self.auto_record_path: Path | None = None
        self.last_state = None
        self._last_state_monotonic: float | None = None

    def _make_live(self) -> LiveControlManager:
        return LiveControlManager(
            self.client, self.config, self.mapping,
            state_provider=lambda: self.last_state,
            state_age_provider=self.state_age_seconds,
        )

    def state_age_seconds(self) -> float | None:
        if self._last_state_monotonic is None:
            return None
        return max(0.0, time.monotonic() - self._last_state_monotonic)

    def connect(self, ip: str, rack: int, slot: int, confirmation_note: str = "") -> None:
        requested_ip = ip.strip()
        confirmed_ip = self.base_config["plc"]["active_ip"]
        base_notes = self.base_config["source_notes"]
        if requested_ip != confirmed_ip and not confirmation_note.strip():
            raise ValueError("输入的 PLC IP 与已确认地址不同，请填写新的现场确认依据/说明")
        self.disconnect()
        self.config = copy.deepcopy(self.base_config)
        self.config["plc"]["active_ip"] = requested_ip
        self.config["plc"]["rack"] = int(rack)
        self.config["plc"]["slot"] = int(slot)
        if requested_ip == confirmed_ip and base_notes.get("site_ip_confirmed") is True:
            self.config["source_notes"]["site_ip_confirmed"] = True
            self.config["source_notes"]["ip_status"] = base_notes.get("ip_status", "SITE_CONFIRMED")
            self.config["source_notes"]["site_confirmation_note"] = base_notes.get("site_confirmation_note", "配置中已确认")
        else:
            self.config["source_notes"]["site_ip_confirmed"] = True
            self.config["source_notes"]["ip_status"] = "CONFIRMED_BY_OPERATOR"
            self.config["source_notes"]["site_confirmation_note"] = confirmation_note.strip()
        self.client = S7Client(self.config)
        self.reader = PLCReader(self.client, self.mapping)
        self.writer = PLCWriter(self.client, self.config, self.mapping)
        self.live = self._make_live()
        self.last_state = None
        self._last_state_monotonic = None
        self.client.connect()
        # 连接成功即启用真实写会话；具体命令仍由 LiveControlManager 联锁。
        self.live.activate()

    def disconnect(self) -> None:
        self.stop_recording()
        self.stop_auto_recording()
        live = getattr(self, 'live', None)
        if live is not None:
            try:
                live.disarm(best_effort=True)
            except Exception:
                pass
        if getattr(self, "client", None) is not None:
            self.client.disconnect()
        self.last_state = None
        self._last_state_monotonic = None

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected())

    @property
    def armed(self) -> bool:
        return bool(getattr(self, 'live', None) and self.live.armed)

    def read_state(self):
        state = self.reader.read_all_state()
        self.last_state = state
        self._last_state_monotonic = time.monotonic()
        state_dict = self.state_dict(state)
        if self.auto_recorder is not None:
            self.auto_recorder.write_dict(state_dict)
        if self.recorder is not None:
            if hasattr(self.recorder, 'write_dict'):
                self.recorder.write_dict(state_dict)
            else:
                self.recorder.write(state)
        return state

    def state_dict(self, state=None) -> dict:
        state = state or self.last_state
        if state is None:
            return {}
        raw = asdict(state)
        extra = raw.pop("additional_values", {})
        raw.update(extra)
        return raw

    def preview(self, name: str, value: bool | float) -> dict:
        if name not in self.mapping:
            raise KeyError(name)
        return self.writer.preview(name, value)

    def arm_live(self, phrase: str, confirmations: dict[str, bool]) -> None:
        self.live.arm(phrase, confirmations)

    def disarm_live(self) -> None:
        self.live.disarm(best_effort=True)

    def live_status(self):
        return self.live.status()

    def request_pulse(self, name: str) -> dict:
        if not self.armed:
            return self.writer.preview(name, True)
        if name == 'remote_mode_button':
            return self.live.select_remote()
        if name == 'local_mode_button':
            return self.live.select_local()
        return self.live.pulse(name)

    def reset_drive_faults(self):
        if not self.armed:
            return {'preview': True, 'action': 'drive_fault_reset'}
        return self.live.reset_drive_faults()


    def request_aux_hold(self, name: str, value: bool) -> dict:
        if not self.armed:
            return self.writer.preview(name, value)
        return self.live.set_aux_hold(name, value)

    def request_speed(self, axis: str, name: str, value: float) -> dict:
        if not self.armed:
            return self.writer.preview(name, value)
        return self.live.set_speed_only(axis, value)

    def request_target(self, axis: str, name: str, value: float) -> dict:
        if not self.armed:
            return self.writer.preview(name, value)
        return self.live.set_target(axis, value)

    def execute_auto_target(self, axis: str, target: float, speed_limit: float):
        """上位机闭环自动到目标；不再触发 PLC 未验证的 auto_start 位。"""
        if not self.armed:
            return {
                'preview': True,
                'kind': 'PC_CLOSED_LOOP_TARGET',
                'axis': axis,
                'target': float(target),
                'speed_limit': float(speed_limit),
            }
        return self.live.execute_auto_target(axis, target, speed_limit)

    def execute_joint_trajectory(self, trajectory, speed_limit: float = 2.0):
        if not self.armed:
            return {'preview': True, 'kind': 'JOINT_TRAJECTORY',
                    'points': len(trajectory.points), 'duration_s': trajectory.duration_s,
                    'speed_limit': float(speed_limit)}
        return self.live.execute_joint_trajectory(trajectory, speed_limit)

    def commanded_speed_percent(self) -> dict[str, float]:
        if not self.live:
            return {'lift': 0.0, 'push': 0.0, 'swing': 0.0}
        return self.live.commanded_speed_percent()

    def cancel_joint_trajectory(self):
        if not self.armed:
            return {'cancelled': False, 'reason': 'not_armed'}
        return self.live.cancel_joint_trajectory()

    def cancel_auto_target(self, axis: str | None = None):
        if not self.armed:
            return {'cancelled': False, 'reason': 'not_armed'}
        return self.live.cancel_auto_target(axis)

    def jog_start(self, axis: str, direction: str, speed: float):
        if not self.armed:
            # 预演也严格按 2026-09-28 真机标定显示：
            # 提升 up=-；推压 forward=+；回转 left=-；履带 forward=+；
            # 物理左履带走 PLC lift/right 通道，物理右履带走 push/left 通道。
            speed_name = {
                'lift': 'lift_right_set_speed',
                'left_track': 'lift_right_set_speed',
                'push': 'push_left_set_speed',
                'right_track': 'push_left_set_speed',
                'swing': 'rotation_set_speed',
            }[axis]
            direction_name = {
                ('lift', 'up'): 'lift_up_or_right_forward',
                ('lift', 'down'): 'lift_down_or_right_backward',
                ('left_track', 'forward'): 'lift_up_or_right_forward',
                ('left_track', 'backward'): 'lift_down_or_right_backward',
                ('push', 'forward'): 'push_forward_or_left_forward',
                ('push', 'backward'): 'push_backward_or_left_backward',
                ('right_track', 'forward'): 'push_forward_or_left_forward',
                ('right_track', 'backward'): 'push_backward_or_left_backward',
                ('swing', 'left'): 'rotation_left',
                ('swing', 'right'): 'rotation_right',
            }[(axis, direction)]

            mag = abs(float(speed))
            signed_speed = {
                ('lift', 'up'): -mag,
                ('lift', 'down'): mag,
                ('push', 'forward'): mag,
                ('push', 'backward'): -mag,
                ('swing', 'left'): -mag,
                ('swing', 'right'): mag,
                ('left_track', 'forward'): mag,
                ('left_track', 'backward'): -mag,
                ('right_track', 'forward'): mag,
                ('right_track', 'backward'): -mag,
            }[(axis, direction)]
            return [
                self.writer.preview(speed_name, signed_speed),
                self.writer.preview(direction_name, True),
            ]

        mapped = {
            ('lift', 'up'): 'up', ('lift', 'down'): 'down',
            ('push', 'forward'): 'forward', ('push', 'backward'): 'backward',
            ('swing', 'left'): 'left', ('swing', 'right'): 'right',
            ('left_track', 'forward'): 'forward', ('left_track', 'backward'): 'backward',
            ('right_track', 'forward'): 'forward', ('right_track', 'backward'): 'backward',
        }[(axis, direction)]
        return self.live.jog_start(axis, mapped, speed)

    def jog_stop(self, axis: str):
        if not self.armed:
            return self.writer.stop_motion()
        return self.live.jog_stop(axis)

    def walk_pair_start(self, action: str, left_speed: float, right_speed: float):
        if not self.armed:
            patterns = {
                'forward': (True, False, True, False),
                'backward': (False, True, False, True),
                'left_turn': (False, True, True, False),
                'right_turn': (True, False, False, True),
            }
            lf, lb, rf, rb = patterns[action]
            left_cmd = abs(float(left_speed)) * (1.0 if lf else -1.0)
            right_cmd = abs(float(right_speed)) * (1.0 if rf else -1.0)
            return [
                # 物理左履带 -> PLC lift/right 通道
                self.writer.preview('lift_right_set_speed', left_cmd),
                # 物理右履带 -> PLC push/left 通道
                self.writer.preview('push_left_set_speed', right_cmd),
                self.writer.preview('lift_up_or_right_forward' if lf else 'lift_down_or_right_backward', True),
                self.writer.preview('push_forward_or_left_forward' if rf else 'push_backward_or_left_backward', True),
            ]
        return self.live.walk_pair_start(action, left_speed, right_speed)

    def walk_pair_stop(self):
        if not self.armed:
            return self.writer.stop_motion()
        return self.live.walk_pair_stop()

    def stop_all(self):
        if not self.armed:
            return self.writer.stop_motion()
        return self.live.safe_stop_all()

    def _session_fieldnames(self) -> list[str]:
        base = ['timestamp', 'source', 'control_mode', 'limit_status', 'errors']
        read_names = [name for name, entry in self.mapping.items() if entry.get('direction') == 'read']
        return base + read_names

    def start_auto_recording(self, directory: Path) -> Path:
        """连接后持续记录 DB400；与手工导出/复现数据互不冲突。"""
        if self.auto_recorder is not None:
            return self.auto_recorder.path
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        path = directory / datetime.now().strftime('自动记录_%Y%m%d_%H%M%S.csv')
        self.auto_recorder = SessionRecorder(path, self._session_fieldnames())
        self.auto_record_path = self.auto_recorder.path
        return self.auto_record_path

    def stop_auto_recording(self) -> None:
        if self.auto_recorder is not None:
            self.auto_recorder.close()
            self.auto_recorder = None

    def start_recording(self, directory: Path) -> Path:
        if self.recorder is not None:
            return self.recorder.path
        self.recorder = CSVRecorder(directory)
        return self.recorder.path

    def stop_recording(self) -> None:
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None

    def start_session_recording(self, path: Path) -> Path:
        if self.recorder is not None:
            return self.recorder.path
        # 固定列包含 ShovelState 基础字段 + variable_map 中全部 DB400 读变量。
        self.recorder = SessionRecorder(Path(path), self._session_fieldnames())
        return self.recorder.path

    def apply_replay_point(self, point, scale: float = 1.0):
        if not self.connected:
            raise RuntimeError('请先连接 PLC')
        scale = float(scale)
        if not 0.01 <= scale <= 1.0:
            raise ValueError('复现倍率必须为 1%..100%')
        return self.live.apply_replay_point(
            point.mode, point.a_speed * scale, point.a_direction,
            point.b_speed * scale, point.b_direction,
            point.c_speed * scale, point.c_direction,
        )

    def write_summary(self) -> dict:
        writes = [v for v in self.mapping.values() if v.get("direction") == "write"]
        return {
            "total": len(writes),
            "valid_address": sum(v.get("valid_address") is True for v in writes),
            "verified_on_plc": sum(v.get("verification_status") == "VERIFIED_ON_PLC" for v in writes),
            "isolated": sum(v.get("valid_address") is not True for v in writes),
            "real_write_implemented": True,
            "armed": self.armed,
        }
