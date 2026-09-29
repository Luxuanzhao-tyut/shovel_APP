"""
读取具名提升编码器：输入Excel映射，输出PLCReader读取的REAL原值。
--offline将1234.5编码到配置指定的模拟窗口，经同一reader读取；不是现场反馈。
现场模式仍须先人工解决IP冲突；本阶段只执行离线分支。
"""
from _common import prepare
from plc.s7_client import S7Client
from plc.offline_client import OfflineReadClient
from plc.variable_map import load_variable_map, max_required_end_offset
from plc.reader import PLCReader
from plc.decoder import encode


def main() -> int:
    """通过相同具名接口读取实测/离线字节，不绕过reader直接解码。"""
    args, config, logger = prepare('读取提升编码器；--offline不连接PLC', True)
    mapping = load_variable_map()
    entry = mapping['lift_encoder']
    logger.info('地址来源：Excel PLC point table；状态：尚未现场验证')
    logger.info('DB%s REAL byte=%s；%s', entry['db'], entry['byte_offset'], entry['note'])
    client = None
    try:
        if args.offline:
            buffer = bytearray(max_required_end_offset(mapping, entry['db']))
            start = entry['byte_offset']  # 来源中的偏移只保存在配置，不在算法硬编码
            value_bytes = encode(1234.5, 'REAL')
            buffer[start:start + len(value_bytes)] = value_bytes
            reader = PLCReader(OfflineReadClient({entry['db']: buffer}), mapping)
            logger.info('OFFLINE 合成测试值，不是设备反馈')
        else:
            client = S7Client(config)
            client.connect()
            reader = PLCReader(client, mapping)
        logger.info('提升编码器 = %s', reader.read_lift_encoder())
        return 0
    except Exception as error:
        logger.error('读取失败：%s', error)
        return 1
    finally:
        if client is not None:
            client.disconnect()


if __name__ == '__main__':
    raise SystemExit(main())
