"""
输入配置采样周期与 PLC 状态，输出新的 CSV；Ctrl+C 关闭文件并打印路径。
--offline 仅记录标为 offline_empty 的空状态，不能作为真实轨迹数据。
修改 CSV 格式请到 csv_recorder.py，修改采样周期请到配置。
"""
import time
from _common import prepare, ROOT
from plc.s7_client import S7Client
from plc.reader import PLCReader
from plc.variable_map import load_variable_map
from models.shovel_state import ShovelState
from recording.csv_recorder import CSVRecorder


def main() -> int:
    """PLC→状态对象→CSV；通信异常立即退出，不把旧数值作为新采样。"""
    args, config, logger = prepare('保存 CSV；--count 0 持续到 Ctrl+C', True)
    client = S7Client(config)
    reader = PLCReader(client, load_variable_map())
    recorder = None
    try:
        if not args.offline:
            client.connect()
        with CSVRecorder(ROOT / 'data') as recorder:
            index = 0
            while args.count == 0 or index < args.count:
                start = time.monotonic()
                state = ShovelState(source='offline_empty', errors={'offline': '没有实测数据'}) if args.offline else reader.read_all_state()
                recorder.write(state)
                index += 1
                time.sleep(max(0, config['runtime']['sample_period_ms'] / 1000 - (time.monotonic() - start)))
        return 0
    except KeyboardInterrupt:
        logger.info('用户停止记录')
        return 0
    except Exception as error:
        logger.error('记录终止：%s', error)
        return 1
    finally:
        client.disconnect()
        if recorder is not None:
            logger.info('CSV 路径：%s', recorder.path.resolve())


if __name__ == '__main__':
    raise SystemExit(main())
