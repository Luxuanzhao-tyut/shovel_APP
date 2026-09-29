"""
输入采样周期和变量表，定时输出主要状态；未知值保持 None。
现场运行需显式执行此脚本，--offline 只验证空状态处理，不模拟安全状态。
调整输出字段可修改此文件，采样周期在配置中修改。
"""
import time
from _common import prepare
from plc.s7_client import S7Client
from plc.variable_map import load_variable_map
from plc.reader import PLCReader
from models.shovel_state import ShovelState


def main() -> int:
    """按配置周期监控，Ctrl+C 或通信异常后断开；不发送停止或控制字。"""
    args, config, logger = prepare('实时状态监控；--count 0 持续运行', True)
    client = S7Client(config)
    reader = PLCReader(client, load_variable_map())
    try:
        if not args.offline:
            client.connect()
        index = 0
        while args.count == 0 or index < args.count:
            start = time.monotonic()
            state = ShovelState(source='offline_empty', errors={'offline': '空状态演示，没有实测数据'}) if args.offline else reader.read_all_state()
            logger.info('%s source=%s 编码器=(%s,%s) 回转=%s 速度=(%s,%s,%s) 模式=%s 故障=%s 未知项=%s',
                        state.timestamp, state.source, state.lift_encoder, state.push_encoder, state.swing_angle,
                        state.lift_actual_speed, state.push_actual_speed, state.swing_actual_speed,
                        state.control_mode, state.fault, len(state.errors))
            index += 1
            time.sleep(max(0, config['runtime']['sample_period_ms'] / 1000 - (time.monotonic() - start)))
        return 0
    except KeyboardInterrupt:
        logger.info('用户停止监控')
        return 0
    except Exception as error:
        logger.error('监控终止：%s', error)
        return 1
    finally:
        client.disconnect()


if __name__ == '__main__':
    raise SystemExit(main())
