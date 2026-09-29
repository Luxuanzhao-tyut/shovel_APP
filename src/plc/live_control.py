"""真实 PLC 写入会话与联锁管理。

证据来源：
- Java S7WriteUtils：BOOL 读-改-写 + 回读校验；REAL float32 大端写入 + 回读校验。
- Java AuxServiceImpl：DB401 0.4 以 100 ms 周期 0/1 翻转作为通信心跳。
- Java ButtonServiceImpl：除本地/远程外，大多数按钮使用 2000 ms 脉冲；本地/远程为保持型互斥位。

本模块不声称替代 PLC 安全程序或硬件急停。未知状态一律拒绝“启动/运动”类写入。
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from plc.decoder import decode, encode
from plc.variable_map import require_address


@dataclass(frozen=True)
class LiveStatus:
    armed: bool
    heartbeat_running: bool
    heartbeat_failures: int
    last_heartbeat_ok: float | None
    state_age_ms: float | None


class VerifiedDB401Writer:
    """只负责“已知地址”的低级、带回读校验写入，不决定机构是否允许动作。"""

    def __init__(self, client, mapping: dict, config: dict):
        self.client = client
        self.mapping = mapping
        self.config = config
        self._lock = threading.RLock()

    def _entry(self, name: str) -> dict:
        if name not in self.mapping:
            raise KeyError(name)
        entry = self.mapping[name]
        if entry.get('direction') != 'write':
            raise ValueError(f'{name} 不是写变量')
        require_address(entry)
        if entry.get('db') != 401:
            raise ValueError(f'{name} 不在 DB401，拒绝真实写')
        return entry

    def read_current(self, name: str):
        entry = self._entry(name)
        if entry['data_type'] == 'BOOL':
            raw = self.client.read_bytes(401, entry['byte_offset'], 1)
            return decode(raw, 'BOOL', bit_offset=entry['bit_offset'])
        size = 4 if entry['data_type'] == 'REAL' else None
        if size is None:
            raise NotImplementedError('当前真实写只实现 BOOL/REAL')
        raw = self.client.read_bytes(401, entry['byte_offset'], size)
        return decode(raw, entry['data_type'])

    def write_bool(self, name: str, value: bool) -> dict:
        if type(value) is not bool:
            raise ValueError('BOOL 写入值必须为 bool')
        return self.write_bool_group({name: value})

    def write_bool_group(self, values: dict[str, bool]) -> dict:
        """在最小连续字节窗口内一次 RMW；保留窗口内未修改位。"""
        if not values:
            raise ValueError('BOOL 组不能为空')
        entries = {name: self._entry(name) for name in values}
        for name, value in values.items():
            if type(value) is not bool or entries[name]['data_type'] != 'BOOL':
                raise ValueError('BOOL 组只接受 BOOL 变量和值')
        offsets = [e['byte_offset'] for e in entries.values()]
        start, end = min(offsets), max(offsets)
        with self._lock:
            buf = bytearray(self.client.read_bytes(401, start, end - start + 1))
            for name, value in values.items():
                e = entries[name]
                idx = e['byte_offset'] - start
                bit = e['bit_offset']
                mask = 1 << bit
                buf[idx] = (buf[idx] | mask) if value else (buf[idx] & ~mask)
            self.client.write_bytes(401, start, bytes(buf))
            verify = self.client.read_bytes(401, start, end - start + 1)
            for name, value in values.items():
                e = entries[name]
                got = decode(verify, 'BOOL', e['byte_offset'] - start, e['bit_offset'])
                if got is not value:
                    raise IOError(f'DB401 回读校验失败：{name} 期望 {value}，实际 {got}')
        return {'written': True, 'kind': 'LIVE_BOOL_GROUP', 'values': dict(values), 'db': 401, 'start': start, 'size': end-start+1}

    def write_real(self, name: str, value: float) -> dict:
        entry = self._entry(name)
        if entry['data_type'] != 'REAL':
            raise ValueError(f'{name} 不是 REAL')
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('REAL 写入必须为有限数值')
        payload = encode(float(value), 'REAL')
        with self._lock:
            self.client.write_bytes(401, entry['byte_offset'], payload)
            raw = self.client.read_bytes(401, entry['byte_offset'], 4)
        got = decode(raw, 'REAL')
        tol = float(self.config.get('live_control', {}).get('real_readback_tolerance', 1e-4))
        if not math.isclose(got, float(value), rel_tol=tol, abs_tol=tol):
            raise IOError(f'DB401 REAL 回读校验失败：{name} 期望 {value}，实际 {got}')
        return {'written': True, 'kind': 'LIVE_REAL', 'name': name, 'value': float(value), 'readback': got,
                'db': 401, 'byte_offset': entry['byte_offset']}

    def write_real_block(self, values: list[tuple[str, float]]) -> dict:
        """将连续 REAL（如 DBD18+DBD22）合并为一次 db_write。"""
        if not values:
            raise ValueError('REAL 组不能为空')
        entries = [(name, self._entry(name), float(value)) for name, value in values]
        if any(e['data_type'] != 'REAL' for _, e, _ in entries):
            raise ValueError('REAL 组只允许 REAL')
        entries.sort(key=lambda x: x[1]['byte_offset'])
        start = entries[0][1]['byte_offset']
        expected = start
        payload = bytearray()
        for name, e, value in entries:
            if e['byte_offset'] != expected:
                raise ValueError('REAL 组地址不连续，拒绝伪原子写')
            payload.extend(encode(value, 'REAL'))
            expected += 4
        with self._lock:
            self.client.write_bytes(401, start, bytes(payload))
            verify = self.client.read_bytes(401, start, len(payload))
        tol = float(self.config.get('live_control', {}).get('real_readback_tolerance', 1e-4))
        results = {}
        for i, (name, _e, value) in enumerate(entries):
            got = decode(verify, 'REAL', i * 4)
            if not math.isclose(got, value, rel_tol=tol, abs_tol=tol):
                raise IOError(f'DB401 REAL 组回读失败：{name} 期望 {value}，实际 {got}')
            results[name] = got
        return {'written': True, 'kind': 'LIVE_REAL_BLOCK', 'values': results, 'db': 401, 'start': start, 'size': len(payload)}

    def pulse(self, name: str, pulse_ms: int) -> dict:
        """同步脉冲：TRUE -> 等待 -> FALSE；异常时尽力复位 FALSE。"""
        if type(pulse_ms) is not int or not 50 <= pulse_ms <= 5000:
            raise ValueError('脉冲宽度必须为 50..5000 ms')
        self.write_bool(name, True)
        try:
            time.sleep(pulse_ms / 1000.0)
        finally:
            self.write_bool(name, False)
        return {'written': True, 'kind': 'LIVE_PULSE', 'name': name, 'pulse_ms': pulse_ms}


class LiveControlManager:
    """每次程序运行都必须显式武装；从 DB400 实时状态计算是否允许写。"""

    HEARTBEAT_NAME = 'communication_heartbeat'
    DIRECTION_NAMES = (
        'lift_up_or_right_forward', 'lift_down_or_right_backward',
        'push_forward_or_left_forward', 'push_backward_or_left_backward',
        'rotation_left', 'rotation_right',
    )
    SPEED_NAMES = ('lift_right_set_speed', 'push_left_set_speed', 'rotation_set_speed')

    # FC199 汇总 fault 的 7 个原始来源。
    # 只有原始位全部明确为 FALSE 时，才允许把 DB400 汇总 fault=True
    # 视作锁存/刷新不一致；任一原始位 TRUE 仍严格拒绝启动/运动。
    DIRECT_FAULT_SOURCES = (
        ('整流/ALM',      16, 21, 0),
        ('提升驱动',      11, 101, 0),
        ('推压驱动',      12, 101, 0),
        ('回转驱动',      13, 3,   0),
        ('左行走驱动',    14, 101, 0),
        ('右行走驱动',    15, 101, 0),
        ('开斗/斗门驱动', 17, 101, 0),
    )

    # 正式 PLC 梯形图 image5 程序段9：
    # 本地 RESET 或远程 Comm_DB(DB28).DBX100.5 触发 1 s TP，
    # 再送到 DB11~DB15 的驱动故障复位位。
    DRIVE_RESET_DB = 28
    DRIVE_RESET_BYTE = 100
    DRIVE_RESET_BIT = 5

    # Main 中已确认的 Comm_DB(DB28) 直接远程支路。
    COMM_DB_HEARTBEAT = (28, 103, 5)   # 心跳
    COMM_DB_RESET = (28, 100, 5)       # FR复位_1
    COMM_DB_LOCAL_MODE = (28, 100, 7)  # FR本地操作_1
    COMM_DB_REMOTE_MODE = (28, 101, 0) # FR远程操作_1

    # 正式 Comm_DB Standard 布局 + Main XML：
    # DB28.DBX101.2 = FR挖掘模式_1
    # DB28.DBX101.3 = FR行走模式_1
    COMM_DB_MODE_BITS = {
        'dig_mode_button':  (28, 101, 2),
        'walk_mode_button': (28, 101, 3),
    }
    MODE_FEEDBACK = {
        'dig_mode_button':  ('dig_mode', 'propel_mode', '挖掘'),
        'walk_mode_button': ('propel_mode', 'dig_mode', '行走'),
    }

    COMM_DB_BRAKE_BITS = {
        'lift_right_release_brake_open':  (28, 101, 4),  # FR提升松闸_1
        'lift_right_release_brake_close': (28, 101, 5),  # FR提升抱闸_1
        'push_left_valve_open':           (28, 102, 2),  # FR推压松闸_1
        'push_left_valve_close':          (28, 102, 3),  # FR推压抱闸_1
        'rotation_brake_open':            (28, 102, 4),  # FR回转松闸_1
        'rotation_brake_close':           (28, 102, 5),  # FR回转抱闸_1
    }

    BRAKE_RELEASE_FEEDBACK = {
        'lift_right_release_brake_open': 'lift_right_release_indicator',
        'push_left_valve_open': 'push_left_release_indicator',
        'rotation_brake_open': 'rotation_release_indicator',
    }

    def __init__(self, client, config: dict, mapping: dict,
                 state_provider: Callable[[], object | None], state_age_provider: Callable[[], float | None]):
        self.client = client
        self.config = config
        self.mapping = mapping
        self.writer = VerifiedDB401Writer(client, mapping, config)
        self.state_provider = state_provider
        self.state_age_provider = state_age_provider
        self.armed = False
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None
        self._hb_toggle = False
        self._hb_failures = 0
        self._last_hb_ok: float | None = None
        self._motion_lock = threading.RLock()
        self._pulse_lock = threading.Lock()
        self._pulse_cancel = threading.Event()
        self._active_pulse_name: str | None = None
        # 记录当前由上位机保持的手动/复现运动方向，用于 DB400 限位实时触发后的定向自动停止。
        self._active_motion: dict[str, str] = {}
        self._rectifier_command_latched = False

        # 上位机闭环“自动到目标”。PLC 自带 auto_start 握手/到位逻辑尚未验证，
        # 真机已出现越过目标不停，因此不再调用 DB401 自动开始位。
        self._auto_target_lock = threading.Lock()
        self._auto_target_cancel = threading.Event()
        self._auto_target_axis: str | None = None

    @property
    def pulse_ms(self) -> int:
        return int(self.config.get('live_control', {}).get('legacy_pulse_ms', 2000))

    def status(self) -> LiveStatus:
        age = self.state_age_provider()
        return LiveStatus(self.armed, bool(self._hb_thread and self._hb_thread.is_alive()), self._hb_failures, self._last_hb_ok, None if age is None else age * 1000)

    def activate(self) -> None:
        """连接 PLC 后自动启用真实写会话。

        UI 不再要求人工“武装”。这里仅打开 DB401 写许可并启动通信心跳；
        运动、模式、电源和制动命令仍必须逐条通过 DB400 新鲜度、远程模式、
        通讯、故障、电源、作业模式、松闸和限位等联锁。连接本身不会主动写运动速度。
        """
        if not self.client.is_connected():
            raise RuntimeError('请先连接 PLC')
        self.config['safety']['write_enabled'] = True
        self.config['safety']['dry_run'] = False
        self.armed = True
        # 上位机作为远程控制端时，同时保持 Main 所需的 Comm_DB.FR远程操作_1。
        # PLC 现场“样机_远程”硬件条件仍由 PLC 自己判断。
        self._ensure_comm_remote_authority()
        self._start_heartbeat()

    def arm(self, phrase: str, confirmations: dict[str, bool]) -> None:
        if not self.client.is_connected():
            raise RuntimeError('请先连接 PLC')
        required_phrase = str(self.config.get('live_control', {}).get('arm_phrase', '')).strip()
        if not required_phrase or phrase.strip() != required_phrase:
            raise RuntimeError('武装口令不正确')
        required = ('area_clear', 'hard_estop_ready', 'control_authority', 'low_speed_test')
        missing = [key for key in required if confirmations.get(key) is not True]
        if missing:
            raise RuntimeError('真实写入拒绝：现场确认项未全部勾选')
        # 武装前要求 DB400 至少有一帧新鲜反馈；不要求已经处于远程模式。
        self._require_fresh_state()
        self.config['safety']['write_enabled'] = True
        self.config['safety']['dry_run'] = False
        self.armed = True
        try:
            # 武装时先把运动输出安全清零，再启动心跳。
            self.safe_stop_all()
            self._start_heartbeat()
        except Exception:
            self.disarm(best_effort=False)
            raise

    def disarm(self, best_effort: bool = True) -> None:
        # 先取消仍在 TRUE 保持期内的脉冲，等待其 finally 把位复位，再关闭写许可。
        self._auto_target_cancel.set()
        self._pulse_cancel.set()
        if self._pulse_lock.acquire(timeout=1.0):
            self._pulse_lock.release()
        if best_effort and self.armed and self.client.is_connected():
            try:
                self.safe_clear_transients()
            except Exception:
                pass
            try:
                self.safe_stop_all()
            except Exception:
                pass
        self._stop_heartbeat()
        if self.armed and self.client.is_connected():
            try:
                ldb, lbyte, lbit = self.COMM_DB_LOCAL_MODE
                rdb, rbyte, rbit = self.COMM_DB_REMOTE_MODE
                self._write_raw_bool_verified(rdb, rbyte, rbit, False)
                self._write_raw_bool_verified(ldb, lbyte, lbit, False)
            except Exception:
                pass
        self._rectifier_command_latched = False
        self.armed = False
        self.config['safety']['write_enabled'] = False
        self.config['safety']['dry_run'] = True

    def _require_armed(self) -> None:
        if not self.armed or self.config['safety'].get('write_enabled') is not True or self.config['safety'].get('dry_run') is not False:
            raise RuntimeError('真实写入未武装')
        if not self.client.is_connected():
            raise RuntimeError('PLC 已离线')

    def _require_fresh_state(self):
        state = self.state_provider()
        age = self.state_age_provider()
        max_age = float(self.config.get('live_control', {}).get('max_state_age_ms', 600)) / 1000.0
        if state is None or age is None or age > max_age:
            raise RuntimeError(f'DB400 状态过期/未知（要求 <= {int(max_age*1000)} ms）')
        return state

    def read_direct_fault_sources(self) -> dict[str, bool]:
        """直接读取 FC199 汇总 fault 的 7 个原始故障源，只读。"""
        self._require_armed()
        result: dict[str, bool] = {}
        try:
            for label, db, byte_offset, bit_offset in self.DIRECT_FAULT_SOURCES:
                raw = bytes(self.client.read_bytes(db, byte_offset, 1))
                if len(raw) != 1:
                    raise IOError(f'DB{db}.DBX{byte_offset}.{bit_offset} 读取长度异常')
                result[label] = bool(raw[0] & (1 << bit_offset))
        except Exception as exc:
            raise RuntimeError(f'无法核验 PLC 原始故障源，按有故障处理：{exc}') from exc
        return result

    def _write_raw_bool_verified(self, db: int, byte_offset: int, bit_offset: int, value: bool) -> None:
        """对已由 PLC 源码确认的单个 BOOL 做读-改-写并回读校验。"""
        self._require_armed()
        raw = bytearray(self.client.read_bytes(db, byte_offset, 1))
        if len(raw) != 1:
            raise IOError(f'DB{db}.DBX{byte_offset}.{bit_offset} 读取长度异常')
        mask = 1 << bit_offset
        raw[0] = (raw[0] | mask) if value else (raw[0] & ~mask)
        self.client.write_bytes(db, byte_offset, bytes(raw))
        verify = bytes(self.client.read_bytes(db, byte_offset, 1))
        got = bool(verify[0] & mask)
        if got is not bool(value):
            raise IOError(
                f'DB{db}.DBX{byte_offset}.{bit_offset} 回读校验失败：'
                f'期望 {bool(value)}，实际 {got}'
            )

    def _wait_state_attr(self, attr: str, expected: bool, timeout_s: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while time.monotonic() < deadline:
            try:
                state = self._require_fresh_state()
                if getattr(state, attr, None) is expected:
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        try:
            state = self._require_fresh_state()
            return getattr(state, attr, None) is expected
        except Exception:
            return False

    def _ensure_comm_remote_authority(self) -> None:
        """保持 Comm_DB 的远程操作位有效。

        Main 中 FR复位/FR松闸支路前面还串联“远程操作”。
        仅写 FR复位/FR松闸而没有 FR远程操作_1 时，机构控制链不会真正生效。
        """
        self._require_armed()
        ldb, lbyte, lbit = self.COMM_DB_LOCAL_MODE
        rdb, rbyte, rbit = self.COMM_DB_REMOTE_MODE
        self._write_raw_bool_verified(ldb, lbyte, lbit, False)
        self._write_raw_bool_verified(rdb, rbyte, rbit, True)

    def _pulse_raw_bool_verified(self, db: int, byte_offset: int, bit_offset: int,
                                 pulse_ms: int | None = None) -> dict:
        width_ms = int(self.pulse_ms if pulse_ms is None else pulse_ms)
        self._write_raw_bool_verified(db, byte_offset, bit_offset, True)
        try:
            time.sleep(max(0.05, width_ms / 1000.0))
        finally:
            self._write_raw_bool_verified(db, byte_offset, bit_offset, False)
        return {
            'written': True, 'kind': 'RAW_BOOL_PULSE',
            'db': db, 'byte': byte_offset, 'bit': bit_offset,
            'pulse_ms': width_ms,
        }

    def _send_dual_pulse(self, mapped_name: str, raw_spec: tuple[int, int, int]) -> dict:
        """DB401 与 Comm_DB 直接远程支路同时脉冲。"""
        if not self._pulse_lock.acquire(blocking=False):
            raise RuntimeError('已有按钮脉冲正在执行；请等待其复位后再发下一个脉冲')
        self._pulse_cancel.clear()
        self._active_pulse_name = mapped_name
        db, byte_offset, bit_offset = raw_spec
        try:
            self._write_raw_bool_verified(db, byte_offset, bit_offset, True)
            self.writer.write_bool(mapped_name, True)
            self._pulse_cancel.wait(self.pulse_ms / 1000.0)
        finally:
            try:
                self.writer.write_bool(mapped_name, False)
            finally:
                try:
                    self._write_raw_bool_verified(db, byte_offset, bit_offset, False)
                finally:
                    self._active_pulse_name = None
                    self._pulse_lock.release()
        return {
            'written': True, 'kind': 'DUAL_REMOTE_PULSE',
            'name': mapped_name, 'db': db, 'byte': byte_offset,
            'bit': bit_offset, 'pulse_ms': self.pulse_ms,
        }

    def _apply_all_brakes_for_mode_switch(self) -> None:
        """模式切换前：运动输出清零，并让提升/推压/回转全部抱闸。"""
        self.safe_stop_all()

        close_names = (
            'lift_right_release_brake_close',
            'push_left_valve_close',
            'rotation_brake_close',
        )

        if not self._pulse_lock.acquire(blocking=False):
            raise RuntimeError('已有按钮脉冲正在执行；请等待其结束后再切换模式')

        self._pulse_cancel.clear()
        self._active_pulse_name = 'mode_switch_brake_close'
        try:
            # DB401 三个抱闸位同时置 TRUE。
            self.writer.write_bool_group({name: True for name in close_names})

            # Comm_DB 三个 FR抱闸位同步置 TRUE。
            for name in close_names:
                db, byte_offset, bit_offset = self.COMM_DB_BRAKE_BITS[name]
                self._write_raw_bool_verified(db, byte_offset, bit_offset, True)

            self._pulse_cancel.wait(self.pulse_ms / 1000.0)
        finally:
            try:
                self.writer.write_bool_group({name: False for name in close_names})
            finally:
                try:
                    for name in close_names:
                        db, byte_offset, bit_offset = self.COMM_DB_BRAKE_BITS[name]
                        self._write_raw_bool_verified(db, byte_offset, bit_offset, False)
                finally:
                    self._active_pulse_name = None
                    self._pulse_lock.release()

        # mode switch FB 的旧模式退出条件要求机构停止/抱闸。
        cfg = self.config.get('live_control', {})
        timeout_s = float(cfg.get('mode_brake_wait_ms', 6000)) / 1000.0
        deadline = time.monotonic() + max(0.5, timeout_s)
        attrs = (
            'lift_right_release_indicator',
            'push_left_release_indicator',
            'rotation_release_indicator',
        )

        while time.monotonic() < deadline:
            state = self._require_fresh_state()
            if all(getattr(state, a, None) is False for a in attrs):
                return
            time.sleep(0.05)

        state = self._require_fresh_state()
        still_open = [
            cn for cn, attr in zip(
                ('提升/右行走', '推压/左行走', '回转'), attrs
            )
            if getattr(state, attr, None) is True
        ]
        detail = '、'.join(still_open) if still_open else 'PLC制动反馈未全部明确为抱闸'
        raise RuntimeError(f'模式切换前未完成抱闸：{detail}')

    def _switch_work_mode(self, name: str) -> dict:
        """按 PLC mode switch FB 的真实顺序切换挖掘/行走。"""
        if name not in self.MODE_FEEDBACK:
            raise ValueError(name)

        target_attr, opposite_attr, target_cn = self.MODE_FEEDBACK[name]
        opposite_name = (
            'walk_mode_button' if name == 'dig_mode_button'
            else 'dig_mode_button'
        )

        state = self._require_base(remote=True, comm=False, fault_clear=False)
        if getattr(state, target_attr, None) is True:
            return {
                'written': False,
                'kind': 'LIVE_MODE_ALREADY_ACTIVE',
                'mode': target_cn,
            }

        self._ensure_comm_remote_authority()

        # 关键：旧模式不退出，目标模式不会进入。
        self._apply_all_brakes_for_mode_switch()

        # 两条入口都明确撤销相反模式，避免旧模式命令残留。
        self.writer.write_bool(opposite_name, False)
        odb, obyte, obit = self.COMM_DB_MODE_BITS[opposite_name]
        self._write_raw_bool_verified(odb, obyte, obit, False)

        if not self._pulse_lock.acquire(blocking=False):
            raise RuntimeError('已有按钮脉冲正在执行；请等待后再切换模式')

        self._pulse_cancel.clear()
        self._active_pulse_name = name
        db, byte_offset, bit_offset = self.COMM_DB_MODE_BITS[name]
        switched = False
        last_state = None
        cfg = self.config.get('live_control', {})
        timeout_s = float(cfg.get('mode_switch_timeout_ms', 12000)) / 1000.0

        try:
            # 不再只发固定 2 s 脉冲；保持目标模式请求，直到 PLC 真正反馈切换完成。
            self._write_raw_bool_verified(db, byte_offset, bit_offset, True)
            self.writer.write_bool(name, True)

            deadline = time.monotonic() + max(1.0, timeout_s)
            while time.monotonic() < deadline:
                last_state = self._require_fresh_state()
                if (
                    getattr(last_state, target_attr, None) is True
                    and getattr(last_state, opposite_attr, None) is not True
                ):
                    switched = True
                    break
                time.sleep(0.08)
        finally:
            try:
                self.writer.write_bool(name, False)
            finally:
                try:
                    self._write_raw_bool_verified(db, byte_offset, bit_offset, False)
                finally:
                    self._active_pulse_name = None
                    self._pulse_lock.release()

        if not switched:
            last_state = last_state or self._require_fresh_state()
            raise RuntimeError(
                f'PLC 未切换到{target_cn}模式：'
                f'dig_mode={getattr(last_state, "dig_mode", None)}, '
                f'propel_mode={getattr(last_state, "propel_mode", None)}；'
                f'已自动停止并抱闸'
            )

        return {
            'written': True,
            'kind': 'LIVE_MODE_SWITCH_CONFIRMED',
            'mode': target_cn,
            'feedback': target_attr,
            'brakes_applied': True,
        }

    def reset_drive_faults(self, retries: int | None = None) -> dict[str, bool]:
        """执行 PLC 正式远程驱动故障复位链（DB28.DBX100.5）。

        仅做故障复位，不下发任何方向/速度/松闸命令。
        整流必须已运行，运动输出必须为零。
        """
        state = self._require_base(remote=True, comm=False, fault_clear=False)
        self._ensure_comm_remote_authority()
        self._require_power_ready(state)
        self._require_rectifier_start_fault_clear()
        if not self._outputs_quiescent():
            raise RuntimeError('驱动故障复位前必须确认所有运动输出为零')

        cfg = self.config.get('live_control', {})
        pulse_ms = int(cfg.get('drive_fault_reset_pulse_ms', 200))
        settle_ms = int(cfg.get('drive_fault_reset_settle_ms', 1400))
        attempts = int(cfg.get('drive_fault_reset_retries', 2) if retries is None else retries)
        attempts = max(1, attempts)

        last = self.read_direct_fault_sources()
        for _ in range(attempts):
            # 先确保低电平，再制造明确上升沿。PLC 内部 TP 自己保持约 1 s。
            self._write_raw_bool_verified(
                self.DRIVE_RESET_DB, self.DRIVE_RESET_BYTE, self.DRIVE_RESET_BIT, False
            )
            time.sleep(0.05)
            self._write_raw_bool_verified(
                self.DRIVE_RESET_DB, self.DRIVE_RESET_BYTE, self.DRIVE_RESET_BIT, True
            )
            time.sleep(max(0.05, pulse_ms / 1000.0))
            self._write_raw_bool_verified(
                self.DRIVE_RESET_DB, self.DRIVE_RESET_BYTE, self.DRIVE_RESET_BIT, False
            )

            deadline = time.monotonic() + max(0.2, settle_ms / 1000.0)
            while time.monotonic() < deadline:
                time.sleep(0.10)
                last = self.read_direct_fault_sources()
                motor_faults = [
                    name for name, active in last.items()
                    if active and name != '整流/ALM'
                ]
                if not motor_faults:
                    return last

        return last

    def _send_mapped_pulse(self, name: str) -> dict:
        """发送 DB401 旧 Java 同语义脉冲；只负责脉冲本身。"""
        if not self._pulse_lock.acquire(blocking=False):
            raise RuntimeError('已有按钮脉冲正在执行；请等待其复位后再发下一个脉冲')
        self._pulse_cancel.clear()
        self._active_pulse_name = name
        try:
            self.writer.write_bool(name, True)
            self._pulse_cancel.wait(self.pulse_ms / 1000.0)
        finally:
            try:
                self.writer.write_bool(name, False)
            finally:
                self._active_pulse_name = None
                self._pulse_lock.release()
        return {'written': True, 'kind': 'LIVE_PULSE', 'name': name, 'pulse_ms': self.pulse_ms}

    def _release_brake_verified(self, name: str) -> dict:
        """不等待 communication_ok，立即复位驱动并发送真实远程松闸命令。"""
        feedback_attr = self.BRAKE_RELEASE_FEEDBACK[name]
        cfg = self.config.get('live_control', {})
        timeout_s = float(cfg.get('brake_feedback_timeout_ms', 8000)) / 1000.0
        retry_count = max(1, int(cfg.get('brake_release_retries', 2)))

        self._ensure_comm_remote_authority()

        last_faults: dict[str, bool] = {}
        for attempt in range(retry_count):
            last_faults = self.reset_drive_faults(retries=1)
            self._send_dual_pulse(name, self.COMM_DB_BRAKE_BITS[name])

            if self._wait_state_attr(feedback_attr, True, timeout_s):
                return {
                    'written': True,
                    'kind': 'LIVE_BRAKE_RELEASE_CONFIRMED',
                    'name': name,
                    'feedback': feedback_attr,
                    'attempt': attempt + 1,
                }

        active = [label for label, value in last_faults.items() if value]
        detail = ('；当前原始故障：' + '、'.join(active)) if active else ''
        raise RuntimeError(
            f'未反馈实际松闸：命令已发送，但 {feedback_attr}=False{detail}'
        )

    def _require_fault_clear(self, state) -> None:
        # 汇总位明确无故障时直接通过。
        if getattr(state, 'fault', None) is False:
            return

        # 汇总位为 TRUE/未知时，不直接放弃；继续读取更接近源头的 7 个故障位。
        sources = self.read_direct_fault_sources()
        active = [name for name, value in sources.items() if value]
        if active:
            raise RuntimeError('联锁拒绝：PLC 原始故障源有效：' + '、'.join(active))

        # 只有 7 个原始故障位全部为 FALSE 时，才把 DB400 汇总 fault=True
        # 视为锁存/刷新不一致并放行。
        return

    def _require_rectifier_start_fault_clear(self) -> None:
        """整流启动阶段的专用故障核验。

        启动前电机驱动侧可能处于未供电/未就绪状态。若把提升、推压、回转、
        行走、开斗驱动故障都作为“整流启动”的前置条件，会形成启动环路：
        驱动要等整流上电，而整流又被驱动未就绪挡住。

        因此这里只检查整流/ALM自身故障（DB16.DBX21.0）。
        整流启动成功以后，松闸和所有运动仍走 _require_base()，继续严格核验
        全部 7 个原始故障源。
        """
        self._require_armed()
        try:
            raw = bytes(self.client.read_bytes(16, 21, 1))
            if len(raw) != 1:
                raise IOError('DB16.DBX21.0 读取长度异常')
            rectifier_alm = bool(raw[0] & 0x01)
        except Exception as exc:
            raise RuntimeError(f'无法核验整流/ALM故障，拒绝整流启动：{exc}') from exc
        if rectifier_alm:
            raise RuntimeError('联锁拒绝：整流/ALM故障有效')

    def _require_base(self, *, remote: bool = True, comm: bool = True, fault_clear: bool = True):
        self._require_armed()
        state = self._require_fresh_state()
        if remote and getattr(state, 'remote_mode', None) is not True:
            raise RuntimeError('联锁拒绝：PLC 未反馈远程模式')
        if comm and getattr(state, 'communication_ok', None) is not True:
            raise RuntimeError('联锁拒绝：PLC 未反馈通讯正常')
        if fault_clear:
            self._require_fault_clear(state)
        return state

    def _require_power_ready(self, state) -> None:
        if self.config.get('live_control', {}).get('require_high_voltage_for_motion', True):
            if getattr(state, 'additional_values', {}).get('high_voltage_indicator', getattr(state, 'high_voltage_indicator', None)) is not True:
                # high_voltage_indicator 通常是 dataclass additional_values 之外的字段时，state_dict 可见；此处兼容二者。
                if getattr(state, 'high_voltage_indicator', None) is not True:
                    raise RuntimeError('联锁拒绝：高压运行未确认')
        if self.config.get('live_control', {}).get('require_rectifier_for_motion', True):
            plc_rectifier_on = (
                getattr(state, 'additional_values', {}).get(
                    'rectifier_indicator',
                    getattr(state, 'rectifier_indicator', None)
                ) is True
                or getattr(state, 'rectifier_indicator', None) is True
            )
            # 现场简化逻辑：只要本次会话已经完整发送过“整流启动”脉冲，
            # 后续就不再等待 DB400 的 rectifier_indicator 才放行。
            if not plc_rectifier_on and not self._rectifier_command_latched:
                raise RuntimeError('联锁拒绝：本次会话尚未发送整流启动命令')

    def _axis_conditions(self, axis: str):
        # communication_ok 是 PLC 内部心跳反馈，不再单独阻断上位机运动。
        # S7 是否真实在线由 fresh-state/读写异常来保证。
        state = self._require_base(comm=False)
        self._require_power_ready(state)
        if axis in ('lift', 'push', 'swing'):
            if getattr(state, 'dig_mode', None) is not True:
                raise RuntimeError('联锁拒绝：当前不是挖掘模式')
        elif axis in ('left_track', 'right_track', 'walk_pair'):
            if getattr(state, 'propel_mode', None) is not True:
                raise RuntimeError('联锁拒绝：当前不是行走模式')
        else:
            raise ValueError(axis)
        # 2026-09-28 真机标定：
        # PLC 符号中的“右行走”通道实际驱动物理左履带；
        # PLC 符号中的“左行走”通道实际驱动物理右履带。
        if axis in ('lift', 'left_track'):
            if getattr(state, 'lift_right_release_indicator', None) is not True:
                raise RuntimeError('联锁拒绝：提升/物理左履带松闸未确认')
        if axis in ('push', 'right_track'):
            if getattr(state, 'push_left_release_indicator', None) is not True:
                raise RuntimeError('联锁拒绝：推压/物理右履带松闸未确认')
        if axis == 'walk_pair':
            if getattr(state, 'lift_right_release_indicator', None) is not True or getattr(state, 'push_left_release_indicator', None) is not True:
                raise RuntimeError('联锁拒绝：左右行走松闸未同时确认')
        if axis == 'swing' and getattr(state, 'rotation_release_indicator', None) is not True:
            raise RuntimeError('联锁拒绝：回转松闸未确认')
        return state

    def _assert_speed_range(self, value: float) -> None:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('速度必须为有限数值')
        speed_cfg = self.config.get('operator_settings', {}).get('speed', {})
        max_percent = float(speed_cfg.get('max_percent', 10.0))
        lo, hi = -max_percent, max_percent
        if not lo <= float(value) <= hi:
            raise RuntimeError(f'速度限幅拒绝：当前允许范围为 {lo:g}% .. {hi:g}%')

    @staticmethod
    def _signed_jog_speed(axis: str, direction: str, speed: float) -> float:
        """把 UI 的物理方向换成 DB401 REAL 的实机标定符号。

        2026-09-28 真机结果：
        - 提升：up 为负，down 为正；
        - 推压：forward 为正，backward 为负；
        - 回转：left 为负，right 为正；
        - 履带：forward 为正，backward 为负。
        """
        mag = abs(float(speed))
        if axis == 'lift':
            if direction in ('up', 'positive'):
                return -mag
            if direction in ('down', 'negative'):
                return mag
        elif axis == 'push':
            if direction in ('forward', 'positive'):
                return mag
            if direction in ('backward', 'negative'):
                return -mag
        elif axis == 'swing':
            if direction in ('left', 'negative'):
                return -mag
            if direction in ('right', 'positive'):
                return mag
        elif axis in ('left_track', 'right_track'):
            if direction in ('forward', 'positive'):
                return mag
            if direction in ('backward', 'negative'):
                return -mag
        raise ValueError(f'不支持的运动方向：axis={axis}, direction={direction}')

    @staticmethod
    def _canonical_direction(axis: str, direction: str) -> str:
        """把别名统一成 UI 使用的物理方向名称。"""
        table = {
            ('lift', 'up'): 'up', ('lift', 'positive'): 'up',
            ('lift', 'down'): 'down', ('lift', 'negative'): 'down',
            ('push', 'forward'): 'forward', ('push', 'positive'): 'forward',
            ('push', 'backward'): 'backward', ('push', 'negative'): 'backward',
            ('swing', 'left'): 'left', ('swing', 'negative'): 'left',
            ('swing', 'right'): 'right', ('swing', 'positive'): 'right',
            ('left_track', 'forward'): 'forward', ('left_track', 'positive'): 'forward',
            ('left_track', 'backward'): 'backward', ('left_track', 'negative'): 'backward',
            ('right_track', 'forward'): 'forward', ('right_track', 'positive'): 'forward',
            ('right_track', 'backward'): 'backward', ('right_track', 'negative'): 'backward',
        }
        try:
            return table[(axis, direction)]
        except KeyError as exc:
            raise ValueError(f'不支持的运动方向：axis={axis}, direction={direction}') from exc

    def _limit_config(self) -> dict:
        return self.config.get('operator_settings', {}).get('limits', {})

    def _blocked_limit_direction(self, axis: str) -> str:
        cfg = self._limit_config()
        if axis == 'lift':
            value = str(cfg.get('lift_blocked_direction', 'up')).strip().lower()
            if value not in ('up', 'down'):
                raise RuntimeError('限位配置错误：lift_blocked_direction 只能是 up 或 down')
            return value
        if axis == 'push':
            value = str(cfg.get('push_blocked_direction', 'forward')).strip().lower()
            if value not in ('forward', 'backward'):
                raise RuntimeError('限位配置错误：push_blocked_direction 只能是 forward 或 backward')
            return value
        raise ValueError(axis)

    @staticmethod
    def _limit_attr(axis: str) -> str:
        return {'lift': 'lift_limit_triggered', 'push': 'push_limit_triggered'}[axis]

    @staticmethod
    def _axis_cn(axis: str) -> str:
        return {'lift': '提升', 'push': '推压', 'swing': '回转'}[axis]

    @staticmethod
    def _direction_cn(axis: str, direction: str) -> str:
        names = {
            ('lift', 'up'): '提升', ('lift', 'down'): '下放',
            ('push', 'forward'): '推出', ('push', 'backward'): '收回',
            ('swing', 'left'): '左回转', ('swing', 'right'): '右回转',
        }
        return names.get((axis, direction), direction)

    def _check_directional_limit(self, axis: str, direction: str, state) -> None:
        """单一限位只禁止继续撞向限位的一侧，反方向允许退出限位。"""
        if axis not in ('lift', 'push'):
            return
        canonical = self._canonical_direction(axis, direction)
        if getattr(state, self._limit_attr(axis), None) is True:
            blocked = self._blocked_limit_direction(axis)
            if canonical == blocked:
                escape = 'down' if axis == 'lift' and blocked == 'up' else (
                    'up' if axis == 'lift' else ('backward' if blocked == 'forward' else 'forward')
                )
                raise RuntimeError(
                    f'{self._axis_cn(axis)}限位已触发：禁止{self._direction_cn(axis, blocked)}，'
                    f'可{self._direction_cn(axis, escape)}退出限位'
                )

    def _stop_axis_output(self, axis: str) -> list[dict]:
        """不依赖当前联锁状态，按“方向 FALSE -> 速度 0”停止单轴。"""
        self._require_armed()
        with self._motion_lock:
            if axis == 'lift':
                group = {'lift_up_or_right_forward': False, 'lift_down_or_right_backward': False}
                speed_name = 'lift_right_set_speed'
            elif axis == 'push':
                group = {'push_forward_or_left_forward': False, 'push_backward_or_left_backward': False}
                speed_name = 'push_left_set_speed'
            elif axis == 'swing':
                group = {'rotation_left': False, 'rotation_right': False}
                speed_name = 'rotation_set_speed'
            elif axis == 'left_track':
                group = {'lift_up_or_right_forward': False, 'lift_down_or_right_backward': False}
                speed_name = 'lift_right_set_speed'
            elif axis == 'right_track':
                group = {'push_forward_or_left_forward': False, 'push_backward_or_left_backward': False}
                speed_name = 'push_left_set_speed'
            else:
                raise ValueError(axis)
            results = [self.writer.write_bool_group(group), self.writer.write_real(speed_name, 0.0)]
            self._active_motion.pop(axis, None)
            return results

    def handle_state_update(self, state) -> list[dict]:
        """每收到一帧新的 DB400 状态时检查运行中限位。

        这只是上位机的第二层监督保护，不能替代 PLC/硬件限位。当前 UI 以 100 ms 周期
        读取 DB400，因此本保护的发现延迟约为一个采样周期加通信/写入时间。
        """
        if not self.armed or not self.client.is_connected():
            return []
        if self._limit_config().get('auto_stop_on_limit', True) is not True:
            return []
        # 提升/推压限位只在挖掘模式解释，避免其复用通道在行走模式误停履带。
        if getattr(state, 'dig_mode', None) is not True:
            return []

        events: list[dict] = []
        for axis in ('lift', 'push'):
            if getattr(state, self._limit_attr(axis), None) is not True:
                continue
            active_direction = self._active_motion.get(axis)
            if not active_direction:
                continue
            blocked = self._blocked_limit_direction(axis)
            if active_direction != blocked:
                continue
            try:
                self._stop_axis_output(axis)
                escape = 'down' if axis == 'lift' and blocked == 'up' else (
                    'up' if axis == 'lift' else ('backward' if blocked == 'forward' else 'forward')
                )
                events.append({
                    'axis': axis,
                    'severity': 'stop',
                    'message': (
                        f'{self._axis_cn(axis)}限位触发，已自动停止{self._direction_cn(axis, blocked)}；'
                        f'仅允许{self._direction_cn(axis, escape)}退出限位'
                    ),
                })
            except Exception as exc:
                events.append({
                    'axis': axis,
                    'severity': 'error',
                    'message': f'{self._axis_cn(axis)}限位触发，但上位机自动停止写入失败：{exc}',
                })
        return events

    def _outputs_quiescent(self) -> bool:
        try:
            for name in self.SPEED_NAMES:
                if abs(float(self.writer.read_current(name))) > 1e-6:
                    return False
            for name in self.DIRECTION_NAMES:
                if self.writer.read_current(name) is True:
                    return False
            return True
        except Exception as exc:
            raise RuntimeError(f'无法确认 DB401 运动输出已清零：{exc}') from exc

    def safe_clear_transients(self) -> dict:
        """清除除本地/远程保持位和心跳外的所有瞬时 BOOL 命令。

        用于解除武装/退出时，避免开斗、喇叭或被中断的按钮脉冲残留 TRUE。
        """
        self._require_armed()
        names = (
            'auto_unmanned_mode_button', 'jog_unmanned_mode_button',
            'high_voltage_start', 'high_voltage_stop', 'rectifier_start', 'rectifier_stop',
            'emergency_stop_button', 'fault_reset_button', 'dig_mode_button', 'walk_mode_button',
            'lift_right_release_brake_open', 'lift_right_release_brake_close',
            'push_left_valve_open', 'push_left_valve_close',
            'rotation_brake_open', 'rotation_brake_close',
            'bucket_open_command', 'horn_command',
            'lift_right_auto_start', 'push_left_auto_start', 'rotation_auto_start',
        )
        return self.writer.write_bool_group({name: False for name in names})

    def safe_stop_all(self) -> list[dict]:
        """停止顺序：先方向 FALSE，再速度 0。只要求已武装+在线，不依赖远程/故障反馈。"""
        self._auto_target_cancel.set()
        self._require_armed()
        with self._motion_lock:
            results = [self.writer.write_bool_group({name: False for name in self.DIRECTION_NAMES})]
            # DBD18、22 连续；DBD26 单独。
            results.append(self.writer.write_real_block([
                ('lift_right_set_speed', 0.0), ('push_left_set_speed', 0.0),
            ]))
            results.append(self.writer.write_real('rotation_set_speed', 0.0))
            self._active_motion.clear()
            return results

    def select_remote(self) -> dict:
        self._require_armed()
        self._require_fresh_state()
        if not self._outputs_quiescent():
            raise RuntimeError('切换控制权前必须确认 DB401 运动输出为零')
        result = self.writer.write_bool_group({
            'local_mode_button': False,
            'remote_mode_button': True
        })
        self._ensure_comm_remote_authority()
        return result

    def select_local(self) -> dict:
        self._require_armed()
        if not self._outputs_quiescent():
            raise RuntimeError('切换控制权前必须确认 DB401 运动输出为零')
        result = self.writer.write_bool_group({
            'local_mode_button': True,
            'remote_mode_button': False
        })
        ldb, lbyte, lbit = self.COMM_DB_LOCAL_MODE
        rdb, rbyte, rbit = self.COMM_DB_REMOTE_MODE
        self._write_raw_bool_verified(rdb, rbyte, rbit, False)
        self._write_raw_bool_verified(ldb, lbyte, lbit, True)
        return result

    def pulse(self, name: str) -> dict:
        """根据命令种类执行联锁后发命令；松闸必须等 PLC 实际反馈后才算成功。"""
        self._require_armed()

        # 停止类/急停：即使故障存在也允许发。
        if name in ('emergency_stop_button', 'high_voltage_stop'):
            if name == 'emergency_stop_button':
                self._auto_target_cancel.set()
            return self._send_mapped_pulse(name)

        if name in ('lift_right_release_brake_close', 'push_left_valve_close', 'rotation_brake_close'):
            return self._send_dual_pulse(name, self.COMM_DB_BRAKE_BITS[name])

        if name == 'rectifier_stop':
            result = self._send_mapped_pulse(name)
            self._rectifier_command_latched = False
            return result

        if name == 'fault_reset_button':
            self._require_base(remote=True, comm=False, fault_clear=False)
            self._ensure_comm_remote_authority()
            return self._send_dual_pulse(name, self.COMM_DB_RESET)

        if name == 'rectifier_start':
            self._require_base(remote=True, comm=False, fault_clear=False)
            self._require_rectifier_start_fault_clear()
            if not self._outputs_quiescent():
                raise RuntimeError('整流启动前必须确认所有运动输出为零')
            result = self._send_mapped_pulse(name)
            self._rectifier_command_latched = True
            return result

        if name == 'high_voltage_start':
            self._require_base(remote=True, comm=True, fault_clear=True)
            if not self._outputs_quiescent():
                raise RuntimeError('电源启动前必须确认所有运动输出为零')
            return self._send_mapped_pulse(name)

        if name in ('dig_mode_button', 'walk_mode_button'):
            return self._switch_work_mode(name)

        if name in ('auto_unmanned_mode_button', 'jog_unmanned_mode_button'):
            self._require_base(remote=True, comm=False, fault_clear=False)
            if not self._outputs_quiescent():
                raise RuntimeError('模式切换前必须确认所有运动输出为零')
            return self._send_mapped_pulse(name)

        if name in self.BRAKE_RELEASE_FEEDBACK:
            state = self._require_base(remote=True, comm=False, fault_clear=False)
            self._require_power_ready(state)
            self._require_rectifier_start_fault_clear()
            if not self._outputs_quiescent():
                raise RuntimeError('松闸前必须确认所有运动输出为零')
            if name == 'rotation_brake_open' and getattr(state, 'dig_mode', None) is not True:
                raise RuntimeError('回转松闸要求挖掘模式')
            if name == 'lift_right_release_brake_open' and not (
                getattr(state, 'dig_mode', None) is True or getattr(state, 'propel_mode', None) is True
            ):
                raise RuntimeError('提升/右行走松闸要求挖掘或行走模式')
            if name == 'push_left_valve_open' and not (
                getattr(state, 'dig_mode', None) is True or getattr(state, 'propel_mode', None) is True
            ):
                raise RuntimeError('推压/左行走松闸要求挖掘或行走模式')
            return self._release_brake_verified(name)

        if name in ('lift_right_auto_start', 'push_left_auto_start', 'rotation_auto_start'):
            axis = {
                'lift_right_auto_start': 'lift',
                'push_left_auto_start': 'push',
                'rotation_auto_start': 'swing'
            }[name]
            state = self._axis_conditions(axis)
            if axis in ('lift', 'push') and getattr(state, self._limit_attr(axis), None) is True:
                raise RuntimeError(
                    f'{self._axis_cn(axis)}限位已触发；自动到目标方向无法可靠确认，拒绝自动执行'
                )
            return self._send_mapped_pulse(name)

        raise RuntimeError(f'{name} 不在允许的脉冲命令表')

    def set_aux_hold(self, name: str, value: bool) -> dict:
        # FALSE 是撤销/停止方向，尽量允许；TRUE 才要求完整联锁。
        if value is False:
            self._require_armed()
            if name not in ('horn_command', 'bucket_open_command'):
                raise RuntimeError('不是辅助保持命令')
            return self.writer.write_bool(name, False)
        if name == 'horn_command':
            self._require_base(remote=True, comm=True, fault_clear=False)
        elif name == 'bucket_open_command':
            state = self._require_base()
            if getattr(state, 'dig_mode', None) is not True:
                raise RuntimeError('开斗要求挖掘模式')
        else:
            raise RuntimeError('不是辅助保持命令')
        return self.writer.write_bool(name, True)

    def set_target(self, axis: str, value: float) -> dict:
        self._axis_conditions(axis)
        name = {'lift': 'lift_right_target_position', 'push': 'push_left_target_position', 'swing': 'rotation_target_position'}[axis]
        return self.writer.write_real(name, float(value))

    @staticmethod
    def _finite_feedback(value, name: str) -> float:
        try:
            value = float(value)
        except Exception as exc:
            raise RuntimeError(f'{name}反馈不可用') from exc
        if not math.isfinite(value):
            raise RuntimeError(f'{name}反馈不是有限数值')
        return value

    @staticmethod
    def _signed_angle_error_deg(target: float, current: float) -> float:
        """最短角度误差，范围 [-180, 180)。正值表示向右增加角度。"""
        return (float(target) - float(current) + 180.0) % 360.0 - 180.0

    def _auto_target_feedback(self, axis: str, state) -> float:
        if axis == 'lift':
            return self._finite_feedback(getattr(state, 'lift_encoder', None), '提升编码器')
        if axis == 'push':
            return self._finite_feedback(getattr(state, 'push_encoder', None), '推压编码器')
        if axis == 'swing':
            return self._finite_feedback(getattr(state, 'swing_angle', None), '回转角度')
        raise ValueError(axis)

    def _auto_target_error(self, axis: str, target: float, current: float) -> float:
        if axis == 'swing':
            return self._signed_angle_error_deg(target, current)
        return float(target) - float(current)

    @staticmethod
    def _auto_target_direction(axis: str, error: float) -> str:
        # 真机已验证的反馈方向：
        # 提升编码器：向下增大；推压编码器：向前增大；回转角：向右增大。
        if axis == 'lift':
            return 'down' if error > 0 else 'up'
        if axis == 'push':
            return 'forward' if error > 0 else 'backward'
        if axis == 'swing':
            return 'right' if error > 0 else 'left'
        raise ValueError(axis)

    def cancel_auto_target(self, axis: str | None = None) -> dict:
        """取消当前上位机闭环自动到目标，并立即把该轴方向/速度清零。"""
        self._auto_target_cancel.set()
        active = self._auto_target_axis
        if active is None:
            return {'cancelled': False, 'reason': 'no_active_target'}
        if axis is not None and axis != active:
            return {'cancelled': False, 'reason': f'active_axis={active}'}
        try:
            self.jog_stop(active)
        except Exception:
            # 取消事件已经置位；执行线程 finally 仍会再次清零。
            pass
        return {'cancelled': True, 'axis': active}

    def execute_auto_target(self, axis: str, target: float, speed_limit: float) -> dict:
        """上位机闭环自动到目标。

        不再使用 PLC 的 DBD6/10/14 + DBX3.3/3.4/3.5 自动开始链。
        真机 2026-09-28 已证实该链可能越过目标继续运动，且执行结果位始终 FALSE。

        当前实现只复用已经真机跑通的“点动方向 + 速度”接口，并由 DB400
        编码器/角度反馈在上位机闭环监督，到达、越过、反馈异常、限位、超时、
        远离目标或人工取消时立即清零该轴输出。
        """
        self._require_armed()
        target = float(target)
        speed_limit = abs(float(speed_limit))
        if not math.isfinite(target):
            raise ValueError('目标值必须是有限数值')
        self._assert_speed_range(speed_limit)
        if speed_limit <= 0:
            raise ValueError('自动到目标速度必须大于 0')

        cfg = self.config.get('live_control', {})
        auto_max = min(
            float(cfg.get('auto_target_max_percent', 5.0)),
            float(self.config.get('operator_settings', {}).get('speed', {}).get('max_percent', 10.0))
        )
        if speed_limit > auto_max:
            raise RuntimeError(f'自动到目标速度限幅：当前最多允许 {auto_max:g}%')

        if axis not in ('lift', 'push', 'swing'):
            raise ValueError('自动到目标只支持提升、推压、回转')

        # 容差：提升/推压是编码器工程值；回转是角度。
        tolerance = (
            float(cfg.get('auto_target_swing_tolerance_deg', 1.0))
            if axis == 'swing'
            else float(cfg.get('auto_target_encoder_tolerance', 20.0))
        )
        wrong_way_margin = (
            float(cfg.get('auto_target_swing_wrong_way_margin_deg', 2.0))
            if axis == 'swing'
            else float(cfg.get('auto_target_encoder_wrong_way_margin', 60.0))
        )
        timeout_s = float(cfg.get('auto_target_timeout_s', 120.0))
        poll_s = max(0.03, float(cfg.get('auto_target_poll_ms', 80)) / 1000.0)

        if not self._auto_target_lock.acquire(blocking=False):
            raise RuntimeError('已有自动到目标任务正在执行，请先停止当前任务')

        self._auto_target_cancel.clear()
        self._auto_target_axis = axis
        started = False

        try:
            state = self._axis_conditions(axis)
            current = self._auto_target_feedback(axis, state)
            error = self._auto_target_error(axis, target, current)

            if abs(error) <= tolerance:
                return {
                    'status': 'reached',
                    'axis': axis,
                    'target': target,
                    'final': current,
                    'error': error,
                    'moved': False,
                }

            direction = self._auto_target_direction(axis, error)
            self._check_directional_limit(axis, direction, state)

            initial_error = error
            best_abs_error = abs(error)
            wrong_way_count = 0
            started_at = time.monotonic()

            # 只启动一次。之后循环只读反馈，不会反复重发运动命令；
            # 因此人工急停/PLC停止后，上位机不会自己再次启动机构。
            self.jog_start(axis, direction, speed_limit)
            started = True

            while True:
                if self._auto_target_cancel.wait(poll_s):
                    raise RuntimeError('自动到目标已取消')

                if time.monotonic() - started_at > timeout_s:
                    raise RuntimeError(f'自动到目标超时（>{timeout_s:g}s），已停止')

                # 每次循环重新核验新鲜反馈和主要联锁。
                state = self._axis_conditions(axis)
                current = self._auto_target_feedback(axis, state)
                error = self._auto_target_error(axis, target, current)
                abs_error = abs(error)

                # 到达容差范围。
                if abs_error <= tolerance:
                    return {
                        'status': 'reached',
                        'axis': axis,
                        'target': target,
                        'final': current,
                        'error': error,
                        'moved': True,
                    }

                # 已越过目标：立即停，不允许继续朝同一方向跑。
                # 对回转使用最短角误差；目标附近跨零同样有效。
                if initial_error * error <= 0:
                    return {
                        'status': 'crossed',
                        'axis': axis,
                        'target': target,
                        'final': current,
                        'error': error,
                        'moved': True,
                    }

                # 方向错误 / 反馈持续远离目标，连续数帧即停止。
                if abs_error < best_abs_error:
                    best_abs_error = abs_error
                    wrong_way_count = 0
                elif abs_error > best_abs_error + wrong_way_margin:
                    wrong_way_count += 1
                    if wrong_way_count >= 4:
                        raise RuntimeError(
                            f'反馈显示机构正在远离目标：target={target:g}, '
                            f'current={current:g}，已停止'
                        )
                else:
                    wrong_way_count = max(0, wrong_way_count - 1)

        finally:
            if started:
                try:
                    self.jog_stop(axis)
                except Exception:
                    # 如果 PLC 已离线，无法再软件写停；硬急停仍必须可用。
                    pass
            self._auto_target_axis = None
            self._auto_target_cancel.clear()
            self._auto_target_lock.release()

    def set_speed_only(self, axis: str, value: float) -> dict:
        """工程调速：非零时仍要求完整机构联锁；并要求对应方向当前为 FALSE。"""
        self._assert_speed_range(value)
        if abs(float(value)) > 1e-9:
            self._axis_conditions(axis)
            direction_names = {
                'lift': ('lift_up_or_right_forward', 'lift_down_or_right_backward'),
                'push': ('push_forward_or_left_forward', 'push_backward_or_left_backward'),
                'swing': ('rotation_left', 'rotation_right'),
                # 真机物理左右与 PLC 符号左右相反。
                'left_track': ('lift_up_or_right_forward', 'lift_down_or_right_backward'),
                'right_track': ('push_forward_or_left_forward', 'push_backward_or_left_backward'),
            }[axis]
            if any(self.writer.read_current(n) is True for n in direction_names):
                raise RuntimeError('方向位当前为 TRUE；禁止单独改速，请先停止该轴')
        else:
            self._require_armed()
        name = {
            'lift': 'lift_right_set_speed', 'left_track': 'lift_right_set_speed',
            'push': 'push_left_set_speed', 'right_track': 'push_left_set_speed',
            'swing': 'rotation_set_speed',
        }[axis]
        return self.writer.write_real(name, float(value))

    def jog_start(self, axis: str, direction: str, speed: float) -> list[dict]:
        """手动点动启动：按真机标定写有符号速度，再设置对应方向位。"""
        self._assert_speed_range(speed)
        if abs(float(speed)) <= 1e-9:
            raise RuntimeError('点动速度不能为 0')
        state = self._axis_conditions(axis)
        self._check_directional_limit(axis, direction, state)
        signed_speed = self._signed_jog_speed(axis, direction, speed)
        canonical = self._canonical_direction(axis, direction)

        with self._motion_lock:
            if axis == 'lift':
                up = canonical == 'up'
                speed_name = 'lift_right_set_speed'
                group = {'lift_up_or_right_forward': up, 'lift_down_or_right_backward': not up}

            elif axis == 'push':
                fwd = canonical == 'forward'
                speed_name = 'push_left_set_speed'
                group = {'push_forward_or_left_forward': fwd, 'push_backward_or_left_backward': not fwd}

            elif axis == 'swing':
                left = canonical == 'left'
                speed_name = 'rotation_set_speed'
                group = {'rotation_left': left, 'rotation_right': not left}

            elif axis == 'left_track':
                # 真机物理左履带 = PLC “提升/右行走”通道。
                fwd = canonical == 'forward'
                speed_name = 'lift_right_set_speed'
                group = {'lift_up_or_right_forward': fwd, 'lift_down_or_right_backward': not fwd}

            elif axis == 'right_track':
                # 真机物理右履带 = PLC “推压/左行走”通道。
                fwd = canonical == 'forward'
                speed_name = 'push_left_set_speed'
                group = {'push_forward_or_left_forward': fwd, 'push_backward_or_left_backward': not fwd}

            else:
                raise ValueError(axis)

            results = [
                self.writer.write_real(speed_name, signed_speed),
                self.writer.write_bool_group(group),
            ]
            self._active_motion[axis] = canonical
            return results

    def jog_stop(self, axis: str) -> list[dict]:
        return self._stop_axis_output(axis)

    def walk_pair_start(self, action: str, left_speed: float, right_speed: float) -> list[dict]:
        self._assert_speed_range(left_speed)
        self._assert_speed_range(right_speed)
        if abs(left_speed) <= 1e-9 and abs(right_speed) <= 1e-9:
            raise RuntimeError('左右履带速度不能同时为 0')
        self._axis_conditions('walk_pair')

        # 元组顺序：物理左前、物理左后、物理右前、物理右后。
        patterns = {
            'forward': (True, False, True, False),
            'backward': (False, True, False, True),
            'left_turn': (False, True, True, False),
            'right_turn': (True, False, False, True),
        }
        if action not in patterns:
            raise ValueError(action)

        lf, lb, rf, rb = patterns[action]
        left_signed = abs(float(left_speed)) * (1.0 if lf else -1.0)
        right_signed = abs(float(right_speed)) * (1.0 if rf else -1.0)

        with self._motion_lock:
            # 2026-09-28 真机标定：
            # DBD18（PLC“右行走”）实际是物理左履带；
            # DBD22（PLC“左行走”）实际是物理右履带。
            res1 = self.writer.write_real_block([
                ('lift_right_set_speed', left_signed),
                ('push_left_set_speed', right_signed),
            ])
            res2 = self.writer.write_bool_group({
                'lift_up_or_right_forward': lf,
                'lift_down_or_right_backward': lb,
                'push_forward_or_left_forward': rf,
                'push_backward_or_left_backward': rb,
            })
            self._active_motion['walk_pair'] = action
            return [res1, res2]

    def walk_pair_stop(self) -> list[dict]:
        self._require_armed()
        with self._motion_lock:
            res1 = self.writer.write_bool_group({
                'lift_up_or_right_forward': False,
                'lift_down_or_right_backward': False,
                'push_forward_or_left_forward': False,
                'push_backward_or_left_backward': False,
            })
            res2 = self.writer.write_real_block([
                ('lift_right_set_speed', 0.0), ('push_left_set_speed', 0.0),
            ])
            self._active_motion.pop('walk_pair', None)
            self._active_motion.pop('left_track', None)
            self._active_motion.pop('right_track', None)
            return [res1, res2]


    def apply_replay_point(self, mode: str, a_speed: float, a_direction: str,
                           b_speed: float, b_direction: str,
                           c_speed: float = 0.0, c_direction: str = 'stop') -> list[dict]:
        """按一个记录点更新速度/方向；使用 2026-09-28 真机方向与履带映射标定。

        walk 模式中 a=物理左履带、b=物理右履带。
        dig 模式中 a=提升、b=推压、c=回转。
        """
        self._require_armed()
        if mode not in ('dig', 'walk'):
            raise ValueError('mode 必须是 dig 或 walk')
        vals = [a_speed, b_speed] + ([c_speed] if mode == 'dig' else [])
        for value in vals:
            self._assert_speed_range(float(value))

        with self._motion_lock:
            results = []

            if mode == 'walk':
                self._axis_conditions('walk_pair')

                def track_bits(side: str, direction: str) -> dict[str, bool]:
                    if side == 'left':
                        # 物理左履带使用 PLC “提升/右行走”方向位。
                        pos, neg = 'lift_up_or_right_forward', 'lift_down_or_right_backward'
                    elif side == 'right':
                        # 物理右履带使用 PLC “推压/左行走”方向位。
                        pos, neg = 'push_forward_or_left_forward', 'push_backward_or_left_backward'
                    else:
                        raise ValueError(side)
                    if direction == 'forward':
                        return {pos: True, neg: False}
                    if direction == 'backward':
                        return {pos: False, neg: True}
                    if direction == 'stop':
                        return {pos: False, neg: False}
                    raise ValueError(direction)

                directions = {}
                directions.update(track_bits('left', a_direction))
                directions.update(track_bits('right', b_direction))

                left_cmd = (
                    self._signed_jog_speed('left_track', a_direction, a_speed)
                    if a_direction != 'stop' and abs(float(a_speed)) > 1e-9 else 0.0
                )
                right_cmd = (
                    self._signed_jog_speed('right_track', b_direction, b_speed)
                    if b_direction != 'stop' and abs(float(b_speed)) > 1e-9 else 0.0
                )
                results.append(self.writer.write_real_block([
                    ('lift_right_set_speed', left_cmd),
                    ('push_left_set_speed', right_cmd),
                ]))
                results.append(self.writer.write_bool_group(directions))
                self._active_motion['walk_pair'] = 'replay'
                return results

            # dig：只对非零/非 stop 的轴要求对应松闸；模式/电源/故障始终核验。
            self._require_base()
            state = self._require_fresh_state()
            self._require_power_ready(state)
            if getattr(state, 'dig_mode', None) is not True:
                raise RuntimeError('联锁拒绝：当前不是挖掘模式')
            if a_direction != 'stop' and abs(float(a_speed)) > 1e-9:
                lift_state = self._axis_conditions('lift')
                self._check_directional_limit('lift', a_direction, lift_state)
            if b_direction != 'stop' and abs(float(b_speed)) > 1e-9:
                push_state = self._axis_conditions('push')
                self._check_directional_limit('push', b_direction, push_state)
            if c_direction != 'stop' and abs(float(c_speed)) > 1e-9:
                self._axis_conditions('swing')

            dirs = {
                'lift_up_or_right_forward': a_direction == 'up',
                'lift_down_or_right_backward': a_direction == 'down',
                'push_forward_or_left_forward': b_direction == 'forward',
                'push_backward_or_left_backward': b_direction == 'backward',
                'rotation_left': c_direction == 'left',
                'rotation_right': c_direction == 'right',
            }

            lift_cmd = (
                self._signed_jog_speed('lift', a_direction, a_speed)
                if a_direction != 'stop' and abs(float(a_speed)) > 1e-9 else 0.0
            )
            push_cmd = (
                self._signed_jog_speed('push', b_direction, b_speed)
                if b_direction != 'stop' and abs(float(b_speed)) > 1e-9 else 0.0
            )
            swing_cmd = (
                self._signed_jog_speed('swing', c_direction, c_speed)
                if c_direction != 'stop' and abs(float(c_speed)) > 1e-9 else 0.0
            )

            results.append(self.writer.write_real_block([
                ('lift_right_set_speed', lift_cmd),
                ('push_left_set_speed', push_cmd),
            ]))
            results.append(self.writer.write_real('rotation_set_speed', swing_cmd))
            results.append(self.writer.write_bool_group(dirs))
            for axis_name, direction_name, speed_value in (
                ('lift', a_direction, a_speed), ('push', b_direction, b_speed), ('swing', c_direction, c_speed)
            ):
                if direction_name == 'stop' or abs(float(speed_value)) <= 1e-9:
                    self._active_motion.pop(axis_name, None)
                else:
                    self._active_motion[axis_name] = self._canonical_direction(axis_name, direction_name)
            return results

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()
        self._hb_stop.clear()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name='plc-heartbeat', daemon=True)
        self._hb_thread.start()

    def _stop_heartbeat(self) -> None:
        self._hb_stop.set()
        t = self._hb_thread
        if t and t.is_alive() and threading.current_thread() is not t:
            t.join(timeout=0.5)
        self._hb_thread = None

    def _heartbeat_loop(self) -> None:
        period = float(self.config.get('live_control', {}).get('heartbeat_period_ms', 100)) / 1000.0
        max_failures = int(self.config.get('live_control', {}).get('heartbeat_max_failures', 3))
        while not self._hb_stop.is_set() and self.armed and self.client.is_connected():
            start = time.monotonic()
            try:
                self._hb_toggle = not self._hb_toggle
                self.writer.write_bool(self.HEARTBEAT_NAME, self._hb_toggle)
                try:
                    db, byte_offset, bit_offset = self.COMM_DB_HEARTBEAT
                    self._write_raw_bool_verified(
                        db, byte_offset, bit_offset, self._hb_toggle
                    )
                except Exception:
                    pass
                self._hb_failures = 0
                self._last_hb_ok = time.monotonic()
            except Exception:
                self._hb_failures += 1
                if self._hb_failures >= max_failures:
                    # 不能保证还能写成功，但尽力停止；随后关闭本地写许可。
                    try:
                        self._pulse_cancel.set()
                        self.safe_clear_transients()
                    except Exception:
                        pass
                    try:
                        self.safe_stop_all()
                    except Exception:
                        pass
                    self.armed = False
                    self.config['safety']['write_enabled'] = False
                    self.config['safety']['dry_run'] = True
                    break
            wait = period - (time.monotonic() - start)
            if wait > 0:
                self._hb_stop.wait(wait)
