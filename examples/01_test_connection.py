"""
首次现场只读测试：输入配置连接参数，输出连接成功或失败，然后断开。
不读取业务变量、不写入任何字节；核对现场连接参数时使用。
修改连接参数请编辑 config/plc_config.yaml，不改此示例。
"""
from _common import prepare
from plc.s7_client import S7Client


def main() -> int:
    """仅验证 S7 连接生命周期；失败返回非零退出码。"""
    _, config, logger = prepare('仅连接并断开 PLC，不读取或写入变量')
    client = S7Client(config)
    try:
        client.connect()
        logger.info('PLC 连接成功')
        return 0
    except Exception as error:
        logger.error('PLC 连接失败：%s', error)
        return 1
    finally:
        client.disconnect()


if __name__ == '__main__':
    raise SystemExit(main())
