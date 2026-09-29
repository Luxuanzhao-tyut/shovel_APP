from __future__ import annotations

import csv
import os
import queue
import shutil
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from plc.config import PROJECT_ROOT
from trajectory.session_replay import ReplaySession, load_session
from ui.control_facade import ControlFacade


class ShovelControlApp(tk.Tk):
    """露天矿电铲样机控制台主界面。"""

    POLL_MS = 100
    HISTORY_MAX = 18000  # 10 Hz 下约 30 min 的内存历史；完整历史同时持续落盘。

    BG = '#F3F5F7'
    CARD = '#FFFFFF'
    TEXT = '#18212B'
    MUTED = '#66717D'
    BORDER = '#D8DEE5'
    BLUE = '#1769AA'
    BLUE_ACTIVE = '#0D4F86'
    GREEN = '#16794A'
    GREEN_ACTIVE = '#0D5E38'
    RED = '#C62828'
    RED_ACTIVE = '#8F1616'
    ORANGE = '#C56A00'
    ORANGE_ACTIVE = '#914E00'
    DARK = '#27313B'
    LIGHT_ACTIVE = '#E6F2FB'

    def __init__(self) -> None:
        super().__init__()
        self.title('露天矿电铲样机控制台')
        self.configure(bg=self.BG)
        # 按当前显示器自动适配，避免 Windows 缩放或较矮屏幕下界面被裁切。
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self._compact_ui = sh < 1000
        self._very_compact_ui = sh < 820
        self.geometry(f'{min(1680, sw)}x{min(920, max(680, sh - 60))}+0+0')
        self.minsize(min(1180, sw), min(680, max(620, sh - 80)))
        self.after_idle(self._maximize_on_windows)

        self.facade = ControlFacade()
        speed_cfg = self.facade.base_config.get('operator_settings', {}).get('speed', {})
        self._speed_default = float(speed_cfg.get('default_percent', 10.0))
        self._speed_max = float(speed_cfg.get('max_percent', 10.0))
        self._speed_step = float(speed_cfg.get('step_percent', 1.0))
        self._auto_speed_min = float(speed_cfg.get('auto_min_percent', 1.0))
        limit_cfg = self.facade.base_config.get('operator_settings', {}).get('limits', {})
        self._lift_blocked_direction = str(limit_cfg.get('lift_blocked_direction', 'up')).lower()
        self._push_blocked_direction = str(limit_cfg.get('push_blocked_direction', 'forward')).lower()
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._state_queue: queue.Queue = queue.Queue(maxsize=4)
        self._action_queue: queue.Queue = queue.Queue()
        self._replay_session: ReplaySession | None = None
        self._replay_thread: threading.Thread | None = None
        self._replay_stop = threading.Event()
        self._replay_active = False
        self._remote_start_running = False
        self._rectifier_command_latched = False
        self._brake_ui_latched = {
            'lift_right_release_indicator': None,
            'push_left_release_indicator': None,
            'rotation_release_indicator': None,
        }
        self._last_state_dict: dict = {}

        self._history: deque[tuple[str, dict]] = deque(maxlen=self.HISTORY_MAX)
        self._history_follow_live = True
        self._history_updating_scale = False
        self._auto_record_path: Path | None = None
        self._read_rows: list[tuple[str, str, str]] = self._build_read_rows()

        self._mode_buttons: dict[str, ttk.Button] = {}
        self._brake_buttons: dict[str, tuple[ttk.Button, ttk.Button]] = {}
        self._motion_buttons: list[ttk.Button] = []
        self._motion_button_meta: dict[ttk.Button, tuple[str, str]] = {}
        self._active_motion_buttons: set[ttk.Button] = set()

        self._configure_style()
        self._build_header()
        self._build_safety_bar()
        self._build_main_area()
        self._build_footer()
        self._drain_queues()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    @staticmethod
    def _runtime_root() -> Path:
        import sys
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).resolve().parent
        return PROJECT_ROOT

    def _maximize_on_windows(self) -> None:
        if os.name != 'nt':
            return
        try:
            self.state('zoomed')
        except tk.TclError:
            pass

    def _build_read_rows(self) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        for key, entry in self.facade.mapping.items():
            if entry.get('direction') != 'read' or entry.get('reserved') is True:
                continue
            label = str(entry.get('display_name') or entry.get('source_name') or key)
            unit = str(entry.get('unit') or '')
            if unit.upper() == 'UNKNOWN':
                unit = ''
            rows.append((key, label, unit))
        rows.sort(key=lambda item: (
            int(self.facade.mapping[item[0]].get('byte_offset') or 0),
            int(self.facade.mapping[item[0]].get('bit_offset') or 0),
        ))
        return rows

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure('.', font=('Microsoft YaHei UI', 9 if self._compact_ui else 10), background=self.BG, foreground=self.TEXT)
        style.configure('TFrame', background=self.BG)
        style.configure('Card.TFrame', background=self.CARD)
        style.configure('Card.TLabelframe', background=self.CARD, bordercolor=self.BORDER, relief='solid')
        style.configure('Card.TLabelframe.Label', background=self.CARD, foreground=self.TEXT,
                        font=('Microsoft YaHei UI', 10 if self._compact_ui else 11, 'bold'))
        style.configure('Title.TLabel', background=self.BG, foreground=self.TEXT,
                        font=('Microsoft YaHei UI', 17 if self._compact_ui else 20, 'bold'))
        style.configure('Sub.TLabel', background=self.BG, foreground=self.MUTED,
                        font=('Microsoft YaHei UI', 9))
        style.configure('Status.TLabel', background=self.CARD, foreground=self.TEXT,
                        font=('Microsoft YaHei UI', 8 if self._compact_ui else 9, 'bold'), padding=(6, 3 if self._compact_ui else 5))
        style.configure('Value.TLabel', background=self.CARD, foreground=self.TEXT,
                        font=('Microsoft YaHei UI', 10 if self._compact_ui else 11, 'bold'))
        style.configure('DataValue.TLabel', background=self.CARD, foreground=self.TEXT,
                        font=('Microsoft YaHei UI', 10 if self._compact_ui else 12, 'bold'))
        style.configure('Muted.TLabel', background=self.CARD, foreground=self.MUTED,
                        font=('Microsoft YaHei UI', 9))
        style.configure('Hint.TLabel', background=self.CARD, foreground=self.MUTED,
                        font=('Microsoft YaHei UI', 8))
        # 所有可点击按钮在 normal / active / pressed 状态下保持完全相同的几何尺寸。
        # 只改变颜色，不改变 border / relief / padding，避免点击时触发布局重算导致页面“弹动”。
        button_padding = (10, 5 if self._compact_ui else 8)
        button_font = ('Microsoft YaHei UI', 9 if self._compact_ui else 10, 'bold')
        style.configure('Control.TButton', borderwidth=0, relief='flat', padding=button_padding, font=button_font)
        style.map('Control.TButton', relief=[('pressed', 'flat'), ('active', 'flat')])
        style.configure('Small.TButton', borderwidth=0, relief='flat', padding=(6, 4),
                        font=('Microsoft YaHei UI', 8 if self._compact_ui else 9))
        style.map('Small.TButton', relief=[('pressed', 'flat'), ('active', 'flat')])

        for name, color in [('Danger', self.RED), ('Warn', self.ORANGE), ('Primary', self.BLUE),
                            ('Good', self.GREEN), ('Dark', self.DARK)]:
            pressed_color = self.BLUE_ACTIVE if name == 'Primary' else (
                self.RED_ACTIVE if name == 'Danger' else
                self.ORANGE_ACTIVE if name == 'Warn' else
                self.GREEN_ACTIVE if name == 'Good' else color
            )
            style.configure(f'{name}.TButton', background=color, foreground='white',
                            borderwidth=0, relief='flat', padding=button_padding, font=button_font)
            style.map(f'{name}.TButton',
                      background=[('pressed', pressed_color), ('active', color)],
                      relief=[('pressed', 'flat'), ('active', 'flat')],
                      foreground=[('disabled', '#E6E6E6')])

        style.configure('MotionActive.TButton', background=self.GREEN_ACTIVE, foreground='white',
                        borderwidth=0, relief='flat', padding=button_padding, font=button_font)
        style.map('MotionActive.TButton',
                  background=[('active', self.GREEN_ACTIVE), ('pressed', self.GREEN_ACTIVE)],
                  relief=[('pressed', 'flat'), ('active', 'flat')])

        style.configure('PulseActive.TButton', background=self.BLUE_ACTIVE, foreground='white',
                        borderwidth=0, relief='flat', padding=button_padding, font=button_font)
        style.map('PulseActive.TButton',
                  background=[('active', self.BLUE_ACTIVE), ('pressed', self.BLUE_ACTIVE)],
                  relief=[('pressed', 'flat'), ('active', 'flat')])

        style.configure('StateOn.TButton', background=self.GREEN, foreground='white',
                        borderwidth=0, relief='flat', padding=button_padding, font=button_font)
        style.map('StateOn.TButton',
                  background=[('active', self.GREEN_ACTIVE), ('pressed', self.GREEN_ACTIVE)],
                  relief=[('pressed', 'flat'), ('active', 'flat')])

        style.configure('StateWarn.TButton', background=self.ORANGE, foreground='white',
                        borderwidth=0, relief='flat', padding=button_padding, font=button_font)
        style.map('StateWarn.TButton',
                  background=[('active', self.ORANGE_ACTIVE), ('pressed', self.ORANGE_ACTIVE)],
                  relief=[('pressed', 'flat'), ('active', 'flat')])

        style.configure('Stop.TButton', background=self.RED, foreground='white',
                        borderwidth=0, relief='flat', padding=button_padding, font=button_font)
        style.map('Stop.TButton',
                  background=[('active', self.RED_ACTIVE), ('pressed', self.RED_ACTIVE)],
                  relief=[('pressed', 'flat'), ('active', 'flat')])
        style.configure('Treeview', rowheight=20 if self._compact_ui else 24, font=('Microsoft YaHei UI', 8 if self._compact_ui else 9), background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 8 if self._compact_ui else 9, 'bold'))

    def _card(self, parent, title: str, **grid):
        frame = ttk.LabelFrame(parent, text=title, style='Card.TLabelframe', padding=6 if self._compact_ui else 9)
        frame.grid(**grid)
        return frame

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(10, 4 if self._compact_ui else 8, 10, 3 if self._compact_ui else 6))
        header.pack(fill='x')
        left = ttk.Frame(header)
        left.pack(side='left', fill='x', expand=True)
        ttk.Label(left, text='露天矿电铲样机控制台', style='Title.TLabel').pack(anchor='w')
        right = ttk.Frame(header)
        right.pack(side='right')
        self.conn_var = tk.StringVar(value='PLC：未连接')
        self.comm_var = tk.StringVar(value='心跳：未知')
        self.mode_var = tk.StringVar(value='模式：未知')
        self.fault_var = tk.StringVar(value='故障：未知')
        for var in (self.conn_var, self.comm_var, self.mode_var, self.fault_var):
            ttk.Label(right, textvariable=var, style='Status.TLabel', relief='solid', borderwidth=1).pack(side='left', padx=3)

    def _build_safety_bar(self) -> None:
        # 主工作区统一为三列两行：右侧历史数据跨两行贯通到底。
        self.workspace = ttk.Frame(self, padding=(12, 0, 12, 6))
        self.workspace.pack(fill='both', expand=True)
        self.workspace.columnconfigure(0, weight=4, uniform='maincol')
        self.workspace.columnconfigure(1, weight=7, uniform='maincol')
        self.workspace.columnconfigure(2, weight=4, uniform='maincol')
        self.workspace.rowconfigure(0, weight=0)
        self.workspace.rowconfigure(1, weight=1)

        # 顶部左：连接与紧急操作。
        c = self._card(self.workspace, '连接与紧急操作', row=0, column=0, sticky='nsew', padx=(0, 4), pady=(0, 4))
        ttk.Label(c, text='PLC IP', style='Muted.TLabel').pack(anchor='w')
        self.ip_var = tk.StringVar(value=self.facade.base_config['plc']['active_ip'])
        ttk.Entry(c, textvariable=self.ip_var, width=18).pack(fill='x', pady=(2, 8))
        row = ttk.Frame(c, style='Card.TFrame'); row.pack(fill='x')
        self.connect_btn = ttk.Button(row, text='连接 PLC', style='Primary.TButton', command=self._connect)
        self.connect_btn.pack(side='left', fill='x', expand=True, padx=(0, 3))
        ttk.Button(row, text='断开', style='Dark.TButton', command=self._disconnect).pack(side='left', fill='x', expand=True, padx=(3, 0))
        rr = ttk.Frame(c, style='Card.TFrame'); rr.pack(fill='x', pady=(8, 0))
        self.emergency_btn = ttk.Button(rr, text='急停', style='Stop.TButton', command=self._emergency_stop)
        self.emergency_btn.pack(side='left', fill='x', expand=True, padx=(0, 3))
        self.reset_btn = ttk.Button(rr, text='复位', style='Warn.TButton')
        self.reset_btn.configure(command=lambda b=self.reset_btn: self._pulse('fault_reset_button', '复位', b, base_style='Warn.TButton'))
        self.reset_btn.pack(side='left', fill='x', expand=True, padx=(3, 0))

        # 顶部中：整流与模式 + 松闸/抱闸。
        c = self._card(self.workspace, '整流与模式 / 松闸抱闸', row=0, column=1, sticky='nsew', padx=4, pady=(0, 4))
        r1 = ttk.Frame(c, style='Card.TFrame'); r1.pack(fill='x')
        rect_on = self._btn(r1, '整流启动', None, 'Good')
        rect_off = self._btn(r1, '整流停止', None, 'Danger')
        rect_on.configure(command=lambda b=rect_on: self._remote_rectifier_start(b))
        rect_off.configure(command=lambda b=rect_off: self._pulse('rectifier_stop', '整流停止', b, base_style='Danger.TButton'))
        rect_on.pack(side='left', expand=True, fill='x', padx=2)
        rect_off.pack(side='left', expand=True, fill='x', padx=2)
        self._mode_buttons['rectifier_start'] = rect_on
        self._mode_buttons['rectifier_stop'] = rect_off
        r2 = ttk.Frame(c, style='Card.TFrame'); r2.pack(fill='x', pady=(5, 0))
        for text_btn, name, state_key in [
            ('远程', 'remote_mode_button', 'remote_mode'), ('本地', 'local_mode_button', 'local_mode'),
            ('挖掘', 'dig_mode_button', 'dig_mode'), ('行走', 'walk_mode_button', 'propel_mode'),
            ('自动', 'auto_unmanned_mode_button', 'auto_unmanned_mode'), ('点动', 'jog_unmanned_mode_button', 'jog_unmanned_mode')]:
            b = self._btn(r2, text_btn, None, 'Primary')
            b.configure(command=lambda n=name, t=text_btn, bb=b: self._pulse(n, t, bb))
            b.pack(side='left', expand=True, fill='x', padx=2)
            self._mode_buttons[state_key] = b
        ttk.Separator(c).pack(fill='x', pady=(5, 4))
        self._build_brake_panel(c)

        # 右侧整列：实时 / 历史数据，从顶部贯通到底部。
        history = self._card(self.workspace, '实时 / 历史数据（DB400）', row=0, column=2, rowspan=2,
                             sticky='nsew', padx=(4, 0), pady=(0, 0))
        self._build_history_panel(history)

    def _build_main_area(self) -> None:
        # 下方左：挖掘机构 + 行走控制。
        left = self._card(self.workspace, '挖掘机构 / 行走控制', row=1, column=0, sticky='nsew',
                          padx=(0, 4), pady=(4, 0))
        self.axis_speed_vars = {'lift': tk.DoubleVar(value=self._speed_default), 'push': tk.DoubleVar(value=self._speed_default), 'swing': tk.DoubleVar(value=self._speed_default)}
        self.axis_feedback_vars = {}
        self._axis_panel(left, '提升', 'lift', 'up', '↑ 提升', 'down', '↓ 下放', 'lift_encoder', 'lift_actual_speed')
        self._axis_panel(left, '推压', 'push', 'forward', '→ 推出', 'backward', '← 收回', 'push_encoder', 'push_actual_speed')
        self._axis_panel(left, '回转', 'swing', 'left', '↶ 左回转', 'right', '↷ 右回转', 'swing_angle', 'swing_actual_speed')
        self._build_walk_controls(left)

        # 下方中：上半辅助/数据/复现，下半关键机构反馈。
        middle = ttk.Frame(self.workspace)
        middle.grid(row=1, column=1, sticky='nsew', padx=4, pady=(4, 0))
        middle.columnconfigure(0, weight=1)
        middle.rowconfigure(0, weight=0)
        middle.rowconfigure(1, weight=1)

        center = self._card(middle, '辅助操作 / 数据 / 复现', row=0, column=0, sticky='ew', pady=(0, 4))
        aux = ttk.Frame(center, style='Card.TFrame'); aux.pack(fill='x')
        self._hold_button(aux, 'bucket_open_command', '开 斗').pack(side='left', fill='x', expand=True, padx=(0, 4))
        self._hold_button(aux, 'horn_command', '喇 叭').pack(side='left', fill='x', expand=True, padx=4)

        ttk.Separator(center).pack(fill='x', pady=4 if self._compact_ui else 7)
        ttk.Label(center, text='自动到目标', style='Value.TLabel').pack(anchor='w')
        ttk.Label(
            center,
            text='提升/推压输入编码器目标值；回转输入角度。单次只输入 1 个目标。',
            style='Hint.TLabel'
        ).pack(anchor='w', pady=(0, 2))

        target_box = ttk.Frame(center, style='Card.TFrame')
        target_box.pack(fill='x', pady=(1, 0))

        self.target_vars = {
            'lift': tk.DoubleVar(value=0.0),
            'push': tk.DoubleVar(value=0.0),
            'swing': tk.DoubleVar(value=0.0),
        }

        # 自动到目标默认采用更低速度；后台硬限制最高 5%。
        auto_default = min(2.0, float(self._speed_max))
        self.auto_speed_vars = {
            'lift': tk.DoubleVar(value=auto_default),
            'push': tk.DoubleVar(value=auto_default),
            'swing': tk.DoubleVar(value=auto_default),
        }
        self.auto_current_vars = {
            axis: tk.StringVar(value='当前 --') for axis in ('lift', 'push', 'swing')
        }
        self.auto_result_vars = {
            axis: tk.StringVar(value='待命') for axis in ('lift', 'push', 'swing')
        }
        self.auto_execute_buttons = {}
        self.auto_cancel_buttons = {}

        header = ttk.Frame(target_box, style='Card.TFrame')
        header.pack(fill='x', pady=(0, 1))
        ttk.Label(header, text='', width=4, style='Hint.TLabel').pack(side='left')
        ttk.Label(header, text='当前位置', width=14, style='Hint.TLabel').pack(side='left')
        ttk.Label(header, text='目标值', width=10, style='Hint.TLabel').pack(side='left')
        ttk.Label(header, text='速度%', width=7, style='Hint.TLabel').pack(side='left')

        axis_rows = [
            ('lift', '提升'),
            ('push', '推压'),
            ('swing', '回转'),
        ]
        for axis, title in axis_rows:
            row = ttk.Frame(target_box, style='Card.TFrame')
            row.pack(fill='x', pady=1)

            ttk.Label(row, text=title, style='Value.TLabel', width=4).pack(side='left')
            ttk.Label(
                row,
                textvariable=self.auto_current_vars[axis],
                style='Muted.TLabel',
                width=14
            ).pack(side='left')

            # 单目标输入框，不支持逗号多点。
            ttk.Entry(
                row,
                textvariable=self.target_vars[axis],
                width=10
            ).pack(side='left', padx=(0, 4))

            ttk.Spinbox(
                row,
                from_=0.5,
                to=min(5.0, float(self._speed_max)),
                increment=0.5,
                textvariable=self.auto_speed_vars[axis],
                width=6
            ).pack(side='left', padx=(0, 4))

            ttk.Button(
                row,
                text='取当前',
                style='Control.TButton',
                width=7,
                command=lambda a=axis: self._take_current_target(a)
            ).pack(side='left', padx=2)

            btn = ttk.Button(
                row,
                text='执行',
                style='Good.TButton',
                width=7,
                command=lambda a=axis: self._execute_auto_target(a)
            )
            btn.pack(side='left', padx=2)
            self.auto_execute_buttons[axis] = btn

            cancel_btn = ttk.Button(
                row,
                text='停止',
                style='Warn.TButton',
                width=6,
                command=lambda a=axis: self._cancel_auto_target(a)
            )
            cancel_btn.pack(side='left', padx=2)
            self.auto_cancel_buttons[axis] = cancel_btn

            ttk.Label(
                row,
                textvariable=self.auto_result_vars[axis],
                style='Hint.TLabel',
                width=16
            ).pack(side='left', padx=(4, 0))

        ttk.Separator(center).pack(fill='x', pady=4 if self._compact_ui else 7)
        ttk.Label(center, text='数据记录 / 导入复现', style='Value.TLabel').pack(anchor='w')
        self.auto_record_var = tk.StringVar(value='')
        data_row = ttk.Frame(center, style='Card.TFrame'); data_row.pack(fill='x', pady=(2, 2))
        ttk.Button(data_row, text='导出记录', style='Primary.TButton', command=self._export_auto_record).pack(side='left', fill='x', expand=True, padx=(0, 2))
        ttk.Button(data_row, text='导入历史 CSV', style='Control.TButton', command=self._import_replay).pack(side='left', fill='x', expand=True, padx=(2, 0))
        self.replay_info_var = tk.StringVar(value='尚未导入复现数据')
        replay_row = ttk.Frame(center, style='Card.TFrame'); replay_row.pack(fill='x', pady=(2, 0))
        ttk.Label(replay_row, text='复现倍率', style='Muted.TLabel').pack(side='left')
        self.replay_scale_var = tk.IntVar(value=100)
        ttk.Spinbox(replay_row, from_=1, to=100, textvariable=self.replay_scale_var, width=5).pack(side='left', padx=4)
        ttk.Label(replay_row, text='%', style='Muted.TLabel').pack(side='left')
        self.replay_start_btn = ttk.Button(replay_row, text='开始复现', style='Good.TButton', command=self._start_replay)
        self.replay_start_btn.pack(side='left', fill='x', expand=True, padx=(8, 2))
        ttk.Button(replay_row, text='结束复现', style='Warn.TButton', command=self._stop_replay).pack(side='left', fill='x', expand=True, padx=(2, 0))

        feedback = self._card(middle, '关键机构反馈', row=1, column=0, sticky='nsew', pady=(4, 0))
        self._build_key_feedback(feedback)

    def _build_walk_controls(self, parent) -> None:
        ttk.Separator(parent).pack(fill='x', pady=(3, 5))
        ttk.Label(parent, text='行走控制', style='Value.TLabel').pack(anchor='w', pady=(0, 3))

        # 速度设定独占一行，避免方向键和独立履带控制相互挤压。
        speed = ttk.Frame(parent, style='Card.TFrame')
        speed.pack(fill='x', pady=(0, 4))
        self.left_track_speed_var = tk.DoubleVar(value=self._speed_default)
        self.right_track_speed_var = tk.DoubleVar(value=self._speed_default)
        speed.columnconfigure(1, weight=1)
        speed.columnconfigure(3, weight=1)
        ttk.Label(speed, text='左履带速度 %', style='Muted.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Spinbox(speed, from_=0, to=self._speed_max, increment=self._speed_step, textvariable=self.left_track_speed_var, width=7).grid(row=0, column=1, sticky='w', padx=(4, 14))
        ttk.Label(speed, text='右履带速度 %', style='Muted.TLabel').grid(row=0, column=2, sticky='w')
        ttk.Spinbox(speed, from_=0, to=self._speed_max, increment=self._speed_step, textvariable=self.right_track_speed_var, width=7).grid(row=0, column=3, sticky='w', padx=(4, 0))

        # 整车行走方向键居中摆放，充分利用纵向空间，不再与独立履带控制并排。
        pad = ttk.Frame(parent, style='Card.TFrame')
        pad.pack(fill='x', pady=(0, 5))
        for col in range(3):
            pad.columnconfigure(col, weight=1)
        self._walk_hold_button(pad, 'forward', '↑\n前进').grid(row=0, column=1, sticky='ew', padx=4, pady=2, ipady=3)
        self._walk_hold_button(pad, 'left_turn', '←\n左转').grid(row=1, column=0, sticky='ew', padx=4, pady=2, ipady=3)
        ttk.Label(pad, text='松开\n即停', style='Muted.TLabel', anchor='center').grid(row=1, column=1, sticky='nsew', padx=6, pady=2)
        self._walk_hold_button(pad, 'right_turn', '→\n右转').grid(row=1, column=2, sticky='ew', padx=4, pady=2, ipady=3)
        self._walk_hold_button(pad, 'backward', '↓\n后退').grid(row=2, column=1, sticky='ew', padx=4, pady=2, ipady=3)

        ttk.Separator(parent).pack(fill='x', pady=(2, 5))
        ttk.Label(parent, text='左右履带独立控制', style='Value.TLabel').pack(anchor='w', pady=(0, 3))

        # 左右履带各自占一整行，按钮完整显示，也更适合现场快速操作。
        tracks = ttk.Frame(parent, style='Card.TFrame')
        tracks.pack(fill='x')
        self._track_panel(tracks, 0, '左履带', 'left_track', self.left_track_speed_var)
        self._track_panel(tracks, 1, '右履带', 'right_track', self.right_track_speed_var)
        self.walk_feedback_var = tk.StringVar(value='左履带实际转速 --    右履带实际转速 --')
        ttk.Label(parent, textvariable=self.walk_feedback_var, style='Muted.TLabel').pack(anchor='center', pady=(4, 0))

    def _build_brake_panel(self, parent) -> None:
        self._brake_buttons.clear()
        grid = ttk.Frame(parent, style='Card.TFrame')
        grid.pack(fill='x')
        brake_items = [
            ('提升 / 右行走', 'lift_right_release_brake_open', 'lift_right_release_brake_close', 'lift_right_release_indicator'),
            ('推压 / 左行走', 'push_left_valve_open', 'push_left_valve_close', 'push_left_release_indicator'),
            ('回转', 'rotation_brake_open', 'rotation_brake_close', 'rotation_release_indicator'),
        ]
        for col, (title, open_name, close_name, state_key) in enumerate(brake_items):
            cell = ttk.Frame(grid, style='Card.TFrame', padding=(2, 0))
            cell.grid(row=0, column=col, sticky='ew', padx=2)
            grid.columnconfigure(col, weight=1)
            ttk.Label(cell, text=title, style='Value.TLabel', anchor='center').pack(fill='x', pady=(0, 2))
            rr = ttk.Frame(cell, style='Card.TFrame'); rr.pack(fill='x')
            open_b = self._btn(rr, '松闸', None, 'Good')
            close_b = self._btn(rr, '抱闸', None, 'Warn')
            open_b.configure(command=lambda n=open_name, t=title, b=open_b: self._pulse(n, f'{t}松闸', b, base_style='Good.TButton'))
            close_b.configure(command=lambda n=close_name, t=title, b=close_b: self._pulse(n, f'{t}抱闸', b, base_style='Warn.TButton'))
            open_b.pack(side='left', expand=True, fill='x', padx=(0, 2))
            close_b.pack(side='left', expand=True, fill='x', padx=(2, 0))
            self._brake_buttons[state_key] = (open_b, close_b)

    def _build_key_feedback(self, parent) -> None:
        grid = ttk.Frame(parent, style='Card.TFrame')
        grid.pack(fill='both', expand=True, pady=(2, 0))
        self.key_feedback_vars: dict[str, tk.StringVar] = {}
        items = [
            ('提升编码器', 'lift_encoder'), ('推压编码器', 'push_encoder'), ('回转角度', 'swing_angle'),
            ('斗杆倾角', 'bucket_tilt_angle'), ('提升电流', 'lift_current'), ('推压电流', 'push_current'),
            ('回转电流', 'swing_current'), ('提升转矩', 'lift_torque'), ('推压转矩', 'push_torque'),
            ('回转转矩', 'swing_torque'), ('左履带实际转速', 'left_walk_motor_actual_speed'),
            ('右履带实际转速', 'right_walk_motor_actual_speed'),
        ]
        # 1680×896 一类屏幕使用 3 列×4 行，让反馈区自然占满中下部，而不是上面挤一排、下面留空。
        cols = 3 if self._compact_ui else 3
        rows = (len(items) + cols - 1) // cols
        for i, (title, key) in enumerate(items):
            r, c = divmod(i, cols)
            cell = ttk.Frame(grid, style='Card.TFrame', padding=(6, 5))
            cell.grid(row=r, column=c, sticky='nsew', padx=2, pady=2)
            ttk.Label(cell, text=title, style='Hint.TLabel').pack(anchor='w')
            v = tk.StringVar(value='--')
            self.key_feedback_vars[key] = v
            ttk.Label(cell, textvariable=v, style='DataValue.TLabel').pack(anchor='w', pady=(2, 0))
        for c in range(cols):
            grid.columnconfigure(c, weight=1, uniform='feedback_col')
        for r in range(rows):
            grid.rowconfigure(r, weight=1, uniform='feedback_row')

    def _build_history_panel(self, parent) -> None:
        top = ttk.Frame(parent, style='Card.TFrame'); top.pack(fill='x')
        self.history_mode_var = tk.StringVar(value='实时')
        self.history_time_var = tk.StringVar(value='--')
        ttk.Label(top, textvariable=self.history_mode_var, style='Value.TLabel').pack(side='left')
        ttk.Label(top, textvariable=self.history_time_var, style='Muted.TLabel').pack(side='left', padx=8)
        ttk.Button(top, text='回到实时', style='Small.TButton', command=self._history_go_live).pack(side='right')

        columns = ('name', 'value', 'unit')
        tree_frame = ttk.Frame(parent, style='Card.TFrame'); tree_frame.pack(fill='both', expand=True, pady=(6, 5))
        self.data_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', selectmode='browse')
        self.data_tree.heading('name', text='数据项'); self.data_tree.heading('value', text='值'); self.data_tree.heading('unit', text='单位')
        self.data_tree.column('name', width=150, minwidth=110, anchor='w')
        self.data_tree.column('value', width=85, minwidth=70, anchor='e')
        self.data_tree.column('unit', width=45, minwidth=35, anchor='center')
        sb = ttk.Scrollbar(tree_frame, orient='vertical', command=self.data_tree.yview)
        self.data_tree.configure(yscrollcommand=sb.set)
        self.data_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self._tree_items: dict[str, str] = {}
        for key, label, unit in self._read_rows:
            iid = self.data_tree.insert('', 'end', values=(label, '--', unit))
            self._tree_items[key] = iid

        self.history_pos_var = tk.DoubleVar(value=0)
        self.history_scale = ttk.Scale(parent, from_=0, to=1, orient='horizontal', variable=self.history_pos_var,
                                       command=self._history_scale_changed)
        self.history_scale.pack(fill='x', pady=(2, 0))
        self.history_range_var = tk.StringVar(value='')

    def _build_footer(self) -> None:
        footer = ttk.Frame(self, padding=(10, 0, 10, 4))
        footer.pack(fill='x')
        card = ttk.Frame(footer, style='Card.TFrame', padding=(6, 3))
        card.pack(fill='x')
        self.action_var = tk.StringVar(value='当前动作：无')
        self.log_var = tk.StringVar(value='就绪')
        ttk.Label(card, textvariable=self.action_var, style='Value.TLabel').pack(side='left', padx=(0, 10))
        if not self._very_compact_ui:
            ttk.Separator(card, orient='vertical').pack(side='left', fill='y', padx=4)
            ttk.Label(card, textvariable=self.log_var, style='Muted.TLabel').pack(side='left', fill='x', expand=True, padx=4)

    def _btn(self, parent, text, command, kind='Control'):
        return ttk.Button(parent, text=text, style=f'{kind}.TButton', command=command)

    def _axis_panel(self, parent, title, axis, dir1, txt1, dir2, txt2, pos_key, speed_key) -> None:
        f = ttk.Frame(parent, style='Card.TFrame', padding=(2, 3 if self._compact_ui else 6)); f.pack(fill='x')
        head = ttk.Frame(f, style='Card.TFrame'); head.pack(fill='x')
        ttk.Label(head, text=title, style='Value.TLabel', width=7).pack(side='left')
        ttk.Label(head, text='速度 %', style='Muted.TLabel').pack(side='left')
        ttk.Spinbox(head, from_=0, to=self._speed_max, increment=self._speed_step, textvariable=self.axis_speed_vars[axis], width=6).pack(side='left', padx=5)
        pos = tk.StringVar(value='位置 -- / 实际转速 --')
        self.axis_feedback_vars[axis] = (pos, pos_key, speed_key)
        ttk.Label(head, textvariable=pos, style='Hint.TLabel').pack(side='right')
        rr = ttk.Frame(f, style='Card.TFrame'); rr.pack(fill='x', pady=(3 if self._compact_ui else 5, 0))
        b1 = ttk.Button(rr, text=txt1, style='Primary.TButton'); b2 = ttk.Button(rr, text=txt2, style='Primary.TButton')
        b1.pack(side='left', expand=True, fill='x', padx=(0, 3)); b2.pack(side='left', expand=True, fill='x', padx=(3, 0))
        self._bind_motion(b1, axis, dir1, self.axis_speed_vars[axis], f'{title}：{txt1.replace(chr(10), " ")}')
        self._bind_motion(b2, axis, dir2, self.axis_speed_vars[axis], f'{title}：{txt2.replace(chr(10), " ")}')
        ttk.Separator(parent).pack(fill='x', pady=1 if self._compact_ui else 2)

    def _track_panel(self, parent, col, title, axis, speed_var) -> None:
        f = ttk.Frame(parent, style='Card.TFrame', padding=(2, 2))
        f.pack(fill='x', pady=1)
        ttk.Label(f, text=title, style='Value.TLabel', width=6).pack(side='left')
        ff = ttk.Button(f, text='前进', style='Primary.TButton'); ff.pack(side='left', fill='x', expand=True, padx=2)
        bb = ttk.Button(f, text='后退', style='Primary.TButton'); bb.pack(side='left', fill='x', expand=True, padx=2)
        self._bind_motion(ff, axis, 'forward', speed_var, f'{title}前进')
        self._bind_motion(bb, axis, 'backward', speed_var, f'{title}后退')

    def _hold_button(self, parent, name: str, label: str):
        btn = ttk.Button(parent, text=label, style='Control.TButton')
        btn.bind('<ButtonPress-1>', lambda _e, b=btn: self._aux_hold(name, True, b, label))
        btn.bind('<ButtonRelease-1>', lambda _e, b=btn: self._aux_hold(name, False, b, label))
        return btn

    def _walk_hold_button(self, parent, action: str, label: str):
        btn = ttk.Button(parent, text=label, style='Primary.TButton', width=8)
        btn.bind('<ButtonPress-1>', lambda _e, b=btn: self._walk_pair_press(action, b, label.replace('\n', '')))
        btn.bind('<ButtonRelease-1>', lambda _e, b=btn: self._walk_pair_release(b))
        return btn

    def _bind_motion(self, btn, axis, direction, speed_var, label: str) -> None:
        self._motion_buttons.append(btn)
        self._motion_button_meta[btn] = (axis, direction)
        btn.bind('<ButtonPress-1>', lambda _e, b=btn: self._motion_press(axis, direction, speed_var, b, label))
        btn.bind('<ButtonRelease-1>', lambda _e, b=btn: self._motion_release(axis, b))

    def _set_button_active(self, btn: ttk.Button, active: bool, base_style: str = 'Primary.TButton') -> None:
        try:
            btn.configure(style='MotionActive.TButton' if active else base_style)
        except tk.TclError:
            pass
        if active:
            self._active_motion_buttons.add(btn)
        else:
            self._active_motion_buttons.discard(btn)

    def _flash_button(self, btn: ttk.Button | None, base_style='Primary.TButton', ms: int = 700) -> None:
        if btn is None:
            return
        try:
            btn.configure(style='PulseActive.TButton')
            self.after(ms, lambda b=btn, s=base_style: b.winfo_exists() and b.configure(style=s))
        except tk.TclError:
            pass

    # ---------------- connection / polling ----------------
    def _connect(self) -> None:
        try:
            self.facade.connect(self.ip_var.get(), 0, 1, '')
            records_dir = self._runtime_root() / 'records'
            self._auto_record_path = self.facade.start_auto_recording(records_dir)
        except Exception as exc:
            messagebox.showerror('连接失败', str(exc)); self._log(f'连接失败：{exc}'); return
        self._history.clear(); self._history_follow_live = True
        self.conn_var.set('PLC：已连接'); self.connect_btn.configure(text='已连接')
        self.auto_record_var.set(f'自动记录中：{self._auto_record_path.name}')
        self._start_polling()
        self._log(f'PLC 已连接，DB400 已开始持续记录：{self._auto_record_path}')

    def _disconnect(self) -> None:
        self._stop_replay(); self._stop_polling()
        try:
            self.facade.disconnect()
        except Exception as exc:
            self._log(f'断开时提示：{exc}')
        self._rectifier_command_latched = False
        for _k in self._brake_ui_latched:
            self._brake_ui_latched[_k] = None
        self.conn_var.set('PLC：未连接'); self.comm_var.set('心跳：未知'); self.mode_var.set('模式：未知'); self.fault_var.set('故障：未知')
        self.connect_btn.configure(text='连接 PLC'); self.action_var.set('当前动作：无')
        if self._auto_record_path:
            self.auto_record_var.set(f'上一份自动记录：{self._auto_record_path.name}')
        self._log('PLC 已断开；自动记录已安全关闭。')

    def _start_polling(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop.clear(); self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name='plc-poll'); self._poll_thread.start()

    def _stop_polling(self) -> None:
        self._poll_stop.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)
        self._poll_thread = None

    def _poll_loop(self) -> None:
        while not self._poll_stop.wait(self.POLL_MS / 1000.0):
            try:
                state = self.facade.read_state()
                try:
                    while self._state_queue.qsize() > 2:
                        self._state_queue.get_nowait()
                    self._state_queue.put_nowait(('state', state))
                except queue.Full:
                    pass
            except Exception as exc:
                try: self._state_queue.put_nowait(('error', str(exc)))
                except queue.Full: pass
                time.sleep(0.2)

    def _drain_queues(self) -> None:
        # 重要：任何单帧 UI 刷新异常都不能让 Tk.after 链停止。
        # 自动 CSV 记录是在 PLC 轮询线程里完成的，所以过去会出现
        # “CSV 一直在变，但 UI 整体冻结”的现象。
        try:
            try:
                while True:
                    kind, payload = self._state_queue.get_nowait()
                    if kind == 'state':
                        try:
                            self._apply_state(payload)
                        except Exception as exc:
                            # 保留最新 PLC 数据缓存，并继续下一帧。
                            self._log(f'UI刷新提示：{exc}')
                    else:
                        self.comm_var.set('通讯：异常')
                        self._log(f'PLC 读取异常：{payload}')
            except queue.Empty:
                pass

            try:
                while True:
                    ok, label, payload = self._action_queue.get_nowait()
                    self._log(f'{label}：{payload}')
            except queue.Empty:
                pass
        finally:
            # 无论上面发生什么，80 ms 后都必须继续刷新。
            self.after(80, self._drain_queues)

    def _apply_state(self, state) -> None:
        """把一帧 PLC 状态应用到 UI。

        刷新顺序刻意分层：
        1. 顶部模式 + 关键机构参数：必须每帧更新；
        2. 按钮样式/历史树：属于辅助显示，异常不得冻结主显示。
        """
        previous_rectifier = self._last_state_dict.get('rectifier_indicator')
        d = self.facade.state_dict(state)
        self._last_state_dict = d

        # ---------- A. 最关键的实时状态，优先更新 ----------
        stamp = self._display_timestamp(d.get('timestamp'))
        self.comm_var.set('通讯：正常')

        if d.get('remote_mode') is True:
            control_mode = '远程'
        elif d.get('local_mode') is True:
            control_mode = '本地'
        else:
            control_mode = '未知'

        # PLC 真值优先：propel=True 就必须显示行走；
        # 避免个别过渡帧 dig/propel 同时为 True 时仍被“挖掘”抢占。
        if d.get('propel_mode') is True:
            work_mode = '行走'
        elif d.get('dig_mode') is True:
            work_mode = '挖掘'
        else:
            work_mode = '--'
        self.mode_var.set(f'模式：{control_mode} / {work_mode}')

        fault = d.get('fault')
        self.fault_var.set(
            '故障：有' if fault is True
            else '故障：无' if fault is False
            else '故障：未知'
        )

        # 关键机构参数每一帧直接写 StringVar。
        for key, var in self.key_feedback_vars.items():
            var.set(self._fmt(d.get(key)))

        for axis, (var, pos_key, speed_key) in self.axis_feedback_vars.items():
            suffix = ''
            if axis == 'lift' and d.get('lift_limit_triggered') is True:
                suffix = (
                    ' / 上限位：禁提升，可下放'
                    if self._lift_blocked_direction == 'up'
                    else ' / 下限位：禁下放，可提升'
                )
            elif axis == 'push' and d.get('push_limit_triggered') is True:
                suffix = (
                    ' / 限位：禁推出，可收回'
                    if self._push_blocked_direction == 'forward'
                    else ' / 限位：禁收回，可推出'
                )
            var.set(
                f'位置 {self._fmt(d.get(pos_key))} / '
                f'转速 {self._fmt(d.get(speed_key))}{suffix}'
            )

        auto_pos_keys = {
            'lift': 'lift_encoder',
            'push': 'push_encoder',
            'swing': 'swing_angle',
        }
        if hasattr(self, 'auto_current_vars'):
            for axis in ('lift', 'push', 'swing'):
                unit = '°' if axis == 'swing' else ''
                self.auto_current_vars[axis].set(
                    f'当前 {self._fmt(d.get(auto_pos_keys[axis]))}{unit}'
                )

        self.walk_feedback_var.set(
            f'左履带实际转速 {self._fmt(d.get("left_walk_motor_actual_speed"))}    '
            f'右履带实际转速 {self._fmt(d.get("right_walk_motor_actual_speed"))}'
        )

        # ---------- B. 整流状态日志 ----------
        current_rectifier = d.get('rectifier_indicator')
        if current_rectifier is True and previous_rectifier is not True:
            self._log('PLC 反馈：整流运行。')
        elif current_rectifier is False and previous_rectifier is True:
            self._log('PLC 反馈：整流停止。')

        # ---------- C. 辅助 UI；任何异常都不能冻结 A 区 ----------
        try:
            self._update_feedback_styles(d)
        except Exception as exc:
            self._log(f'按钮状态刷新提示：{exc}')

        try:
            self._update_limit_button_states(d)
        except Exception as exc:
            self._log(f'限位显示刷新提示：{exc}')

        try:
            for event in self.facade.consume_safety_events():
                axis = event.get('axis')
                if axis:
                    for btn, (btn_axis, _direction) in list(self._motion_button_meta.items()):
                        if btn_axis == axis:
                            self._set_button_active(btn, False)
                message = str(event.get('message') or '限位保护动作')
                self.action_var.set(f'安全保护：{message}')
                self._log(message)
        except Exception as exc:
            self._log(f'安全事件显示提示：{exc}')

        # ---------- D. 历史缓存/右侧数据树 ----------
        try:
            self._history.append((stamp, dict(d)))
            self._update_history_scale()

            if self._history_follow_live:
                self.history_mode_var.set('实时')
                self.history_time_var.set(stamp)

                # 不再读取 Treeview 旧 values 再拼装，直接使用初始化时的 label/unit，
                # 避免某个 Treeview item values 异常导致整个刷新循环中断。
                for key, label, unit in self._read_rows:
                    iid = self._tree_items.get(key)
                    if iid:
                        self.data_tree.item(
                            iid,
                            values=(label, self._fmt(d.get(key)), unit)
                        )
        except Exception as exc:
            self._log(f'实时数据表刷新提示：{exc}')

    def _update_limit_button_states(self, d: dict) -> None:
        """限位触发时只禁用继续撞向限位的一侧，反方向保持可用。"""
        lift_trip = d.get('lift_limit_triggered') is True
        push_trip = d.get('push_limit_triggered') is True
        for btn, (axis, direction) in self._motion_button_meta.items():
            blocked = False
            if axis == 'lift' and lift_trip:
                blocked = direction == self._lift_blocked_direction
            elif axis == 'push' and push_trip:
                blocked = direction == self._push_blocked_direction
            try:
                btn.configure(state='disabled' if blocked else 'normal')
            except tk.TclError:
                pass

    def _update_feedback_styles(self, d: dict) -> None:
        for key in ('remote_mode', 'local_mode', 'dig_mode', 'propel_mode', 'auto_unmanned_mode', 'jog_unmanned_mode'):
            b = self._mode_buttons.get(key)
            if b:
                b.configure(style='StateOn.TButton' if d.get(key) is True else 'Primary.TButton')

        # 整流按钮不再等待 PLC 整流反馈。
        # 本次会话只要已经成功发送过整流启动脉冲，就保持“已启动”。
        rect = d.get('rectifier_indicator')
        start_btn = self._mode_buttons.get('rectifier_start')
        stop_btn = self._mode_buttons.get('rectifier_stop')
        if self._rectifier_command_latched or rect is True:
            if start_btn:
                start_btn.configure(text='已启动', style='StateOn.TButton')
            if stop_btn:
                stop_btn.configure(text='整流停止', style='Danger.TButton')
        elif self._remote_start_running:
            if start_btn:
                start_btn.configure(text='启动中…', style='PulseActive.TButton')
        else:
            if start_btn:
                start_btn.configure(text='整流启动', style='Good.TButton')
            if stop_btn:
                stop_btn.configure(text='整流停止', style='Danger.TButton')

        # 松闸/抱闸按钮显示 PLC 的真实反馈状态，而不是仅显示“最后点击了哪个按钮”。
        # released=True  -> 已松闸 / 未抱闸
        # released=False -> 未松闸 / 已抱闸
        for state_key, (open_b, close_b) in self._brake_buttons.items():
            raw_released = d.get(state_key)

            # PLC 明确反馈 True 时，作为正向确认。
            if raw_released is True:
                self._brake_ui_latched[state_key] = True

            latched = self._brake_ui_latched.get(state_key)
            if latched is True:
                open_b.configure(text='已松闸', style='StateOn.TButton')
                close_b.configure(text='未抱闸', style='Warn.TButton')
            elif latched is False:
                open_b.configure(text='未松闸', style='Good.TButton')
                close_b.configure(text='已抱闸', style='StateWarn.TButton')
            elif raw_released is True:
                open_b.configure(text='已松闸', style='StateOn.TButton')
                close_b.configure(text='未抱闸', style='Warn.TButton')
            elif raw_released is False:
                open_b.configure(text='未松闸', style='Good.TButton')
                close_b.configure(text='已抱闸', style='StateWarn.TButton')
            else:
                open_b.configure(text='松闸', style='Good.TButton')
                close_b.configure(text='抱闸', style='Warn.TButton')

    @staticmethod
    def _display_timestamp(value) -> str:
        if not value:
            return time.strftime('%H:%M:%S.%f')[:-3]
        text = str(value)
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
            return dt.astimezone().strftime('%H:%M:%S.%f')[:-3]
        except Exception:
            return text[-12:]

    @staticmethod
    def _fmt(v) -> str:
        if v is None or v == '': return '--'
        if isinstance(v, bool): return 'ON' if v else 'OFF'
        if isinstance(v, float): return f'{v:.3f}'
        return str(v)

    # ---------------- history ----------------
    def _update_history_scale(self) -> None:
        n = len(self._history)
        self._history_updating_scale = True
        self.history_scale.configure(to=max(1, n - 1))
        if self._history_follow_live and n:
            self.history_pos_var.set(n - 1)
        self._history_updating_scale = False
        if n:
            first = self._history[0][0]; last = self._history[-1][0]
            self.history_range_var.set(f'{n} 帧缓存 · {first} → {last} · 完整记录持续写入 CSV')
        else:
            self.history_range_var.set('暂无历史数据')

    def _history_scale_changed(self, value) -> None:
        if self._history_updating_scale or not self._history:
            return
        idx = max(0, min(len(self._history) - 1, int(round(float(value)))))
        if idx < len(self._history) - 1:
            self._history_follow_live = False
            self._show_history_index(idx, live=False)
        else:
            self._history_follow_live = True
            self._show_history_index(idx, live=True)

    def _force_live_view(self) -> None:
        """现场控制动作开始时，强制右侧数据显示最新实时帧。"""
        self._history_follow_live = True
        if not self._history:
            self.history_mode_var.set('实时')
            return
        self._history_updating_scale = True
        try:
            self.history_pos_var.set(len(self._history) - 1)
        finally:
            self._history_updating_scale = False
        self._show_history_index(len(self._history) - 1, live=True)

    def _history_go_live(self) -> None:
        if not self._history:
            return
        self._history_follow_live = True
        self._history_updating_scale = True
        self.history_pos_var.set(len(self._history) - 1)
        self._history_updating_scale = False
        self._show_history_index(len(self._history) - 1, live=True)

    def _show_history_index(self, idx: int, live: bool) -> None:
        if not self._history:
            return
        idx = max(0, min(len(self._history) - 1, idx))
        stamp, data = self._history[idx]
        self.history_mode_var.set('实时' if live else '历史')
        self.history_time_var.set(stamp)
        for key, label, unit in self._read_rows:
            iid = self._tree_items.get(key)
            if iid:
                self.data_tree.item(
                    iid,
                    values=(label, self._fmt(data.get(key)), unit)
                )

    # ---------------- actions ----------------
    def _run_action(self, func, label: str) -> None:
        def worker():
            try:
                result = func(); self._action_queue.put((True, label, result))
            except Exception as exc:
                self._action_queue.put((False, label, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _wait_cached_state(self, predicate, timeout_s: float, poll_s: float = 0.10) -> dict:
        """等待 UI 轮询缓存满足条件，不额外并发读取 PLC。"""
        deadline = time.monotonic() + float(timeout_s)
        last = {}
        while time.monotonic() < deadline:
            if not self.facade.connected:
                raise RuntimeError('PLC 已离线')
            last = dict(self._last_state_dict)
            if last and predicate(last):
                return last
            time.sleep(poll_s)
        return last

    def _remote_start_status(self, text: str) -> None:
        """从后台线程安全更新远程启动状态。"""
        def apply():
            self.action_var.set(f'当前动作：{text}')
            self._log(text)
        self.after(0, apply)

    def _remote_rectifier_start(self, btn: ttk.Button | None = None) -> None:
        """最简整流启动：启动命令完整写入后立即放行，不等待 PLC 反馈。"""
        if self._remote_start_running:
            return
        if not self.facade.connected:
            messagebox.showwarning('PLC 未连接', '请先连接 PLC。')
            return

        self._remote_start_running = True
        if btn is not None:
            try:
                btn.configure(state='disabled', text='启动中…', style='PulseActive.TButton')
            except tk.TclError:
                pass
        self.action_var.set('当前动作：整流启动')

        def worker():
            try:
                self.facade.request_pulse('rectifier_start')

                # 命令完整写入后立即认为本次软件会话已经完成整流启动步骤。
                # 不再等待 DB400 rectifier_indicator，不再显示“等待 PLC 反馈”。
                self._rectifier_command_latched = True
                self._action_queue.put((True, '整流启动', '完成'))
                self._remote_start_status('整流已启动')
            except Exception as exc:
                self._rectifier_command_latched = False
                self._action_queue.put((False, '整流启动', str(exc)))
                self._remote_start_status(f'整流启动命令失败：{exc}')
            finally:
                self._remote_start_running = False

                def restore():
                    if btn is None:
                        return
                    try:
                        if self._rectifier_command_latched:
                            btn.configure(
                                state='normal', text='已启动',
                                style='StateOn.TButton'
                            )
                        else:
                            btn.configure(
                                state='normal', text='整流启动',
                                style='Good.TButton'
                            )
                    except tk.TclError:
                        pass

                self.after(0, restore)

        threading.Thread(
            target=worker, daemon=True, name='remote-rectifier-command'
        ).start()

    def _pulse(self, name: str, label: str, btn: ttk.Button | None = None, base_style='Primary.TButton') -> None:
        self._force_live_view()
        self._flash_button(btn, base_style=base_style)
        self.action_var.set(f'当前动作：{label}')

        def action():
            result = self.facade.request_pulse(name)

            brake_open_map = {
                'lift_right_release_brake_open': 'lift_right_release_indicator',
                'push_left_valve_open': 'push_left_release_indicator',
                'rotation_brake_open': 'rotation_release_indicator',
            }
            brake_close_map = {
                'lift_right_release_brake_close': 'lift_right_release_indicator',
                'push_left_valve_close': 'push_left_release_indicator',
                'rotation_brake_close': 'rotation_release_indicator',
            }

            if name in brake_open_map:
                self._brake_ui_latched[brake_open_map[name]] = True
                self.after(0, lambda: self._update_feedback_styles(self._last_state_dict))
            elif name in brake_close_map:
                self._brake_ui_latched[brake_close_map[name]] = False
                self.after(0, lambda: self._update_feedback_styles(self._last_state_dict))

            if (
                name in ('dig_mode_button', 'walk_mode_button')
                and isinstance(result, dict)
                and result.get('kind') == 'LIVE_MODE_SWITCH_CONFIRMED'
            ):
                # 模式切换流程已自动抱闸。
                for _k in self._brake_ui_latched:
                    self._brake_ui_latched[_k] = False

                target_mode = '行走' if name == 'walk_mode_button' else '挖掘'

                def refresh_mode_after_switch():
                    mode = (
                        '远程' if self._last_state_dict.get('remote_mode') is True
                        else '本地' if self._last_state_dict.get('local_mode') is True
                        else '未知'
                    )
                    self.mode_var.set(f'模式：{mode} / {target_mode}')
                    self._update_feedback_styles(self._last_state_dict)

                self.after(0, refresh_mode_after_switch)

            if name == 'rectifier_stop':
                self._rectifier_command_latched = False
                for _k in self._brake_ui_latched:
                    self._brake_ui_latched[_k] = False

                def refresh_rectifier_buttons():
                    start_btn = self._mode_buttons.get('rectifier_start')
                    stop_btn = self._mode_buttons.get('rectifier_stop')
                    if start_btn:
                        start_btn.configure(text='整流启动', style='Good.TButton')
                    if stop_btn:
                        stop_btn.configure(text='已停止', style='StateWarn.TButton')
                    self._update_feedback_styles(self._last_state_dict)

                self.after(0, refresh_rectifier_buttons)
            return result

        self._run_action(action, label)
        self.after(1200, lambda: self.action_var.get() == f'当前动作：{label}' and self.action_var.set('当前动作：无'))

    def _emergency_stop(self) -> None:
        self._stop_replay()
        for b in list(self._active_motion_buttons):
            self._set_button_active(b, False)
        self.action_var.set('当前动作：急停')
        self._flash_button(self.emergency_btn, base_style='Stop.TButton', ms=1200)
        self._run_action(lambda: (self.facade.stop_all(), self.facade.request_pulse('emergency_stop_button')), '急停')

    def _motion_press(self, axis, direction, speed_var, btn, label: str) -> None:
        self._force_live_view()
        if self._replay_active:
            self._log('正在复现，手动运动命令已忽略；请先结束复现。'); return
        try: speed = abs(float(speed_var.get()))
        except Exception: self._log('速度输入无效'); return
        self._set_button_active(btn, True)
        self.action_var.set(f'当前动作：{label} · 设定速度 {speed:g}')
        self._run_action(lambda: self.facade.jog_start(axis, direction, speed), label)

    def _motion_release(self, axis, btn) -> None:
        self._force_live_view()
        self._set_button_active(btn, False)
        if self._replay_active: return
        self.action_var.set('当前动作：无')
        self._run_action(lambda: self.facade.jog_stop(axis), f'{axis}松开停止')

    def _aux_hold(self, name, value, btn, label) -> None:
        self._force_live_view()
        if self._replay_active and value:
            self._log('正在复现，辅助动作已忽略。'); return
        self._set_button_active(btn, value, base_style='Control.TButton')
        self.action_var.set(f'当前动作：{label}' if value else '当前动作：无')
        self._run_action(lambda: self.facade.request_aux_hold(name, value), f'{label}{"按下" if value else "释放"}')

    def _walk_pair_press(self, action, btn, label) -> None:
        self._force_live_view()
        if self._replay_active:
            self._log('正在复现，手动行走命令已忽略；请先结束复现。'); return
        try: ls, rs = abs(float(self.left_track_speed_var.get())), abs(float(self.right_track_speed_var.get()))
        except Exception: self._log('履带速度输入无效'); return
        self._set_button_active(btn, True)
        self.action_var.set(f'当前动作：行走 {label} · 左 {ls:g} / 右 {rs:g}')
        self._run_action(lambda: self.facade.walk_pair_start(action, ls, rs), f'行走:{action}')

    def _walk_pair_release(self, btn) -> None:
        self._force_live_view()
        self._set_button_active(btn, False)
        if self._replay_active: return
        self.action_var.set('当前动作：无')
        self._run_action(self.facade.walk_pair_stop, '行走松开停止')

    def _take_current_target(self, axis: str) -> None:
        key = {'lift': 'lift_encoder', 'push': 'push_encoder', 'swing': 'swing_angle'}[axis]
        value = self._last_state_dict.get(key)
        try:
            value = float(value)
        except Exception:
            self._log('当前反馈值不可用，无法填入目标。')
            return
        self.target_vars[axis].set(value)
        self._log(f'{axis} 已取当前反馈值作为目标：{value:g}')

    def _execute_auto_target(self, axis: str) -> None:
        self._force_live_view()
        if self._replay_active:
            self._log('正在复现，自动到目标命令已忽略。')
            return
        if not self.facade.connected:
            messagebox.showwarning('PLC 未连接', '请先连接 PLC。')
            return

        try:
            target = float(self.target_vars[axis].get())
            speed = abs(float(self.auto_speed_vars[axis].get()))
        except Exception:
            self._log('自动目标或速度输入无效')
            return

        if speed <= 0:
            self._log('自动速度必须大于 0')
            return

        label = {'lift': '提升', 'push': '推压', 'swing': '回转'}[axis]
        target_unit = '°' if axis == 'swing' else ''
        btn = self.auto_execute_buttons.get(axis)
        if btn:
            btn.configure(state='disabled')
        self.auto_result_vars[axis].set('执行中')
        self.action_var.set(
            f'当前动作：{label}到目标 {target:g}{target_unit} · {speed:g}%'
        )
        current_key = {
            'lift': 'lift_encoder',
            'push': 'push_encoder',
            'swing': 'swing_angle',
        }[axis]
        current_now = self._last_state_dict.get(current_key)
        self._log(
            f'{label}自动到目标开始：current={self._fmt(current_now)}{target_unit}, '
            f'target={target:g}{target_unit}, speed={speed:g}%'
        )

        def worker():
            try:
                result = self.facade.execute_auto_target(axis, target, speed)
                status = result.get('status') if isinstance(result, dict) else None
                final = result.get('final') if isinstance(result, dict) else None
                error = result.get('error') if isinstance(result, dict) else None

                if status in ('reached', 'crossed'):
                    text = (
                        f'已到达 {final:.3f}'
                        if isinstance(final, (int, float))
                        else '已到达'
                    )
                    self._action_queue.put((
                        True,
                        f'{label}自动到目标',
                        f'{text}，误差 {error:.3f}' if isinstance(error, (int, float)) else text,
                    ))
                    self.after(0, lambda: self.auto_result_vars[axis].set('已到达'))
                else:
                    self._action_queue.put((True, f'{label}自动到目标', str(result)))
                    self.after(0, lambda: self.auto_result_vars[axis].set('完成'))

            except Exception as exc:
                msg = str(exc)
                self._action_queue.put((False, f'{label}自动到目标', msg))

                if '状态过期' in msg or '反馈' in msg and '不可用' in msg:
                    status_text = '反馈超时停止'
                elif '远离目标' in msg:
                    status_text = '方向异常停止'
                elif '限位' in msg:
                    status_text = '限位停止'
                elif '超时' in msg:
                    status_text = '超时停止'
                elif '取消' in msg:
                    status_text = '已停止'
                else:
                    status_text = '异常停止'

                self.after(
                    0,
                    lambda s=status_text: self.auto_result_vars[axis].set(s)
                )
            finally:
                if btn:
                    self.after(0, lambda: btn.configure(state='normal'))

        threading.Thread(
            target=worker,
            daemon=True,
            name=f'auto-target-{axis}'
        ).start()

    def _cancel_auto_target(self, axis: str) -> None:
        try:
            result = self.facade.cancel_auto_target(axis)
            if result.get('cancelled'):
                self.auto_result_vars[axis].set('停止中')
                self._log(f'{axis} 自动到目标：已发送停止')
            else:
                self._log(f'{axis} 自动到目标：当前没有该轴任务')
        except Exception as exc:
            self._log(f'停止自动到目标失败：{exc}')

    # ---------------- record/export/replay ----------------
    def _export_auto_record(self) -> None:
        src = self._auto_record_path
        if src is None or not src.exists():
            messagebox.showwarning('暂无记录', '请先连接 PLC。连接成功后程序会自动持续记录 DB400。'); return
        name = datetime.now().strftime('电铲完整记录_%Y%m%d_%H%M%S.csv')
        path = filedialog.asksaveasfilename(title='导出当前完整记录副本', defaultextension='.csv', initialfile=name,
                                            filetypes=[('CSV 数据', '*.csv')])
        if not path: return
        try:
            shutil.copyfile(src, path)
            self._log(f'已导出记录副本：{path}')
            messagebox.showinfo('导出完成', f'已导出到：\n{path}\n\n自动记录仍会继续。')
        except Exception as exc:
            messagebox.showerror('导出失败', str(exc))

    def _import_replay(self) -> None:
        path = filedialog.askopenfilename(title='导入历史 CSV', filetypes=[('CSV 数据', '*.csv'), ('所有文件', '*.*')])
        if not path: return
        try: session = load_session(Path(path), self.POLL_MS / 1000.0)
        except Exception as exc: messagebox.showerror('导入失败', str(exc)); return
        self._replay_session = session
        mode = '行走' if session.mode == 'walk' else '挖掘'
        self.replay_info_var.set(f'{Path(path).name}\n{mode} · {session.source_rows} 点 · {session.duration_s:.1f} s')
        self._log(f'已导入复现数据：{Path(path).name}，模式={mode}，点数={session.source_rows}')

    def _start_replay(self) -> None:
        if self._replay_active: return
        if self._replay_session is None:
            messagebox.showwarning('没有数据', '请先点击“导入历史 CSV”。'); return
        if not self.facade.connected:
            messagebox.showwarning('PLC 未连接', '请先连接 PLC。'); return
        try: scale = int(self.replay_scale_var.get()) / 100.0
        except Exception: messagebox.showerror('倍率错误', '复现倍率必须是 1~100%。'); return
        if not 0.01 <= scale <= 1.0:
            messagebox.showerror('倍率错误', '复现倍率必须是 1~100%。'); return
        session = self._replay_session
        self._replay_stop.clear(); self._replay_active = True
        self.replay_start_btn.configure(state='disabled'); self.action_var.set(f'当前动作：复现 {session.path.name}')
        self._log(f'开始复现：{session.path.name}，倍率 {int(scale*100)}%')

        def worker():
            try:
                start = time.monotonic(); t0 = session.points[0].t_s
                for point in session.points:
                    if self._replay_stop.is_set(): break
                    target = start + max(0.0, point.t_s - t0); wait = target - time.monotonic()
                    if wait > 0 and self._replay_stop.wait(wait): break
                    self.facade.apply_replay_point(point, scale)
                self.facade.stop_all()
                if not self._replay_stop.is_set(): self._action_queue.put((True, '速度序列复现', None))
            except Exception as exc:
                try: self.facade.stop_all()
                except Exception: pass
                self._action_queue.put((False, '复现已中止', str(exc)))
            finally:
                self._replay_active = False
                self.after(0, lambda: (self.replay_start_btn.configure(state='normal'), self.action_var.set('当前动作：无')))
        self._replay_thread = threading.Thread(target=worker, daemon=True, name='session-replay'); self._replay_thread.start()

    def _stop_replay(self) -> None:
        if not self._replay_active: return
        self._replay_stop.set(); self._replay_active = False
        try: self.facade.stop_all()
        except Exception: pass
        self.replay_start_btn.configure(state='normal'); self.action_var.set('当前动作：无'); self._log('复现结束。')

    def _log(self, text: str) -> None:
        now = time.strftime('%H:%M:%S'); self.log_var.set(f'[{now}] {text}')

    def _on_close(self) -> None:
        self._stop_replay(); self._stop_polling()
        try: self.facade.disconnect()
        except Exception: pass
        self.destroy()
