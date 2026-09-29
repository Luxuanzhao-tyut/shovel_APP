"""运行离线示例并禁止网络；输出只写 pytest 临时目录；变更示例或退出逻辑时扩展。"""
import runpy
import sys
import socket
import logging
from pathlib import Path
import pytest
from plc.config import PROJECT_ROOT
from plc.s7_client import S7Client


@pytest.mark.parametrize('filename,args', [
    ('01_test_connection.py', ['--help']),
    ('02_read_one_variable.py', ['--offline']),
    ('03_monitor_plc_state.py', ['--offline', '--count', '2']),
    ('04_record_plc_to_csv.py', ['--offline', '--count', '2']),
    ('05_dry_run_write_command.py', []),
    ('06_legacy_trajectory_replay_demo.py', []),
    ('07_show_verified_variable_map.py', []),
    ('08_show_signal_chain.py', []),
])
def test_offline_example_has_no_network(filename, args, monkeypatch, tmp_path):
    """套接字与 S7 连接均禁止，保证离线分支不受将来代码改动影响。"""
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / 'examples'))
    import _common
    monkeypatch.setattr(_common, 'ROOT', tmp_path)
    def forbidden(*args, **kwargs):
        """任何连接尝试立即使测试失败。"""
        raise AssertionError('离线示例禁止网络')
    monkeypatch.setattr(S7Client, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(sys, 'argv', [filename, *args])
    try:
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(PROJECT_ROOT / 'examples' / filename), run_name='__main__')
        assert result.value.code == 0
    finally:
        logger = logging.getLogger('shovel_plc')
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
