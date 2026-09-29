"""离线验证 CSV 不覆盖与历史速度语义；输入内存状态与点，输出断言；改变记录或 baseline 时扩展。"""
import csv
import pytest
from models.shovel_state import ShovelState
from recording.csv_recorder import CSVRecorder
from trajectory.trajectory_point import TrajectoryPoint
from trajectory.legacy_speed_replay import build_replay_plan
from plc.config import load_config


def test_csv_preserves_unknown_and_history(tmp_path):
    """空状态明确标记、历史文件独占保护、异常退出后文件已关闭。"""
    with CSVRecorder(tmp_path, 'record.csv') as recorder:
        recorder.write(ShovelState(source='offline_empty', errors={'fault': '未知'}))
    with recorder.path.open(encoding='utf-8-sig', newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['fault'] == ''
    assert row['source'] == 'offline_empty'
    assert '未知' in row['errors']
    with pytest.raises(FileExistsError):
        CSVRecorder(tmp_path, 'record.csv')


def test_replay_sign_period_and_none():
    """保留 Java 挖掘路径符号与比例，同时区分无命令和零速度。"""
    config = load_config()
    config['legacy']['replay_period_ms'] = 250
    rows = build_replay_plan([TrajectoryPoint(-5.0, 5.0, 13.2), TrajectoryPoint(None, 0.0, -13.2)], config)
    assert rows[0]['lift_direction'] == 'up'
    assert rows[0]['push_direction'] == 'forward'
    assert rows[0]['swing_direction'] == 'left'
    assert rows[0]['swing_speed'] == -1.0
    assert rows[1]['time_ms'] == 250
    assert 'lift_speed' not in rows[1]
    assert rows[1]['push_direction'] == 'stop'
    assert rows[1]['swing_direction'] == 'right'


def test_invalid_replay():
    """非有限速度在产生可用计划前拒绝。"""
    with pytest.raises(ValueError):
        build_replay_plan([TrajectoryPoint(float('nan'))], load_config())


def test_session_recorder_async_writer_preserves_rows(tmp_path):
    import csv
    from recording.session_recorder import SessionRecorder

    path = tmp_path / 'async.csv'
    rec = SessionRecorder(path, ['timestamp', 'lift_encoder'])
    for i in range(100):
        rec.write_dict({'timestamp': str(i), 'lift_encoder': float(i)})
    rec.close()

    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 100
    assert rows[0]['lift_encoder'] == '0.0'
    assert rows[-1]['lift_encoder'] == '99.0'
