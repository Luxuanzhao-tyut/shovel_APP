"""
展示独立来源的部分信号链；输入signal_chains.yaml，输出层级关系与未知转换。
没有PLC客户端，不读取TIA物理区；修改关系前必须获得梯形图或交叉引用证据。
"""
from _common import prepare, ROOT
import yaml


def main() -> int:
    """打印三轴端点，不把同名不同类型的值视为数值相等。"""
    _, _, logger = prepare('只展示部分信号链，不连接PLC')
    # 依据本文件位置定位配置，不依赖运行目录或日志目录。
    from plc.config import PROJECT_ROOT
    with (PROJECT_ROOT / 'config/signal_chains.yaml').open(encoding='utf-8') as stream:
        chains = yaml.safe_load(stream)
    for name, chain in chains.items():
        logger.info('%s: %s → PLC internal conversion %s → %s → PLCReader.%s()；%s',
                    name, chain['input_address'], chain['internal_conversion'], chain['db_address'],
                    chain['python_method'], chain['confidence'])
    logger.info('回转原始源UNKNOWN；候选Tag未进入正式接口。所有地址尚未现场验证。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
