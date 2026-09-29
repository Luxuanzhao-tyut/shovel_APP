"""读取并校验项目配置。"""
from pathlib import Path
import math
import ipaddress
import sys
import yaml

PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def config_dir() -> Path:
    """优先读取 EXE 同级的外部 config，便于现场直接改参数而无需重新打包。"""
    if getattr(sys, "frozen", False):
        external = Path(sys.executable).resolve().parent / "config"
        if (external / "plc_config.yaml").exists():
            return external
    return PROJECT_ROOT / "config"


def load_config(path: Path | None = None) -> dict:
    cfg_dir = config_dir()
    with (path or cfg_dir / 'plc_config.yaml').open(encoding='utf-8-sig') as stream:
        config = yaml.safe_load(stream)
    operator_path = cfg_dir / 'operator_settings.yaml'
    if operator_path.exists():
        with operator_path.open(encoding='utf-8-sig') as stream:
            operator_settings = yaml.safe_load(stream) or {}
    else:
        operator_settings = {
            'speed': {'default_percent': 10.0, 'max_percent': 10.0, 'step_percent': 1.0, 'auto_min_percent': 1.0}
        }
    config['operator_settings'] = operator_settings
    for key in ('write_enabled', 'dry_run'):
        if type(config['safety'].get(key)) is not bool:
            raise ValueError(f'safety.{key} 必须为 YAML 布尔值')
    for section, key in (('runtime', 'sample_period_ms'), ('legacy', 'replay_period_ms')):
        value = config[section][key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{section}.{key} 必须为有限正数')
    live = config.get('live_control', {})
    if not str(live.get('arm_phrase', '')).strip():
        raise ValueError('live_control.arm_phrase 不能为空')
    for key in ('heartbeat_period_ms', 'legacy_pulse_ms', 'max_state_age_ms'):
        value = live.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'live_control.{key} 必须为有限正数')
    rng = live.get('commissioning_speed_range')
    if not isinstance(rng, list) or len(rng) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in rng) or rng[0] >= rng[1]:
        raise ValueError('live_control.commissioning_speed_range 必须为 [min,max]')
    speed_cfg = config.get('operator_settings', {}).get('speed', {})
    for key in ('default_percent', 'max_percent', 'step_percent', 'auto_min_percent'):
        value = speed_cfg.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'operator_settings.speed.{key} 必须为有限正数')
    if speed_cfg['max_percent'] > 100:
        raise ValueError('operator_settings.speed.max_percent 不能超过 100')
    if speed_cfg['default_percent'] > speed_cfg['max_percent']:
        raise ValueError('default_percent 不能大于 max_percent')
    if speed_cfg['auto_min_percent'] > speed_cfg['max_percent']:
        raise ValueError('auto_min_percent 不能大于 max_percent')
    ipaddress.ip_address(config['plc']['active_ip'])
    notes = config['source_notes']
    for key in ('java_source_ip', 'excel_source_ip'):
        ipaddress.ip_address(notes[key])
    if type(notes.get('site_ip_confirmed')) is not bool:
        raise ValueError('site_ip_confirmed 必须显式为布尔值')
    if notes['java_source_ip'] != notes['excel_source_ip']:
        if not notes['site_ip_confirmed'] and notes.get('ip_status') != 'UNRESOLVED_CONFLICT':
            raise ValueError('来源 IP 不同，不能静默消除 UNRESOLVED_CONFLICT')
    if notes['site_ip_confirmed'] and not notes.get('site_confirmation_note'):
        raise ValueError('人工确认 IP 时须填写 site_confirmation_note')
    for key in ('rack', 'slot'):
        if type(config['plc'][key]) is not int or config['plc'][key] < 0:
            raise ValueError(f'plc.{key} 必须为非负整数')
    return config
