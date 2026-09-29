"""
输入配置与示例数值，输出提升设定速度的离线计划；绝对不驱动设备。
即使用户将配置切换为真实写，本示例也只调用 preview，不连接 PLC。
Java 没证明百分比换算，因此演示值 5 只能称原始设定值，不宣称 5%。
修改示例数值请在配置 legacy.demo_speed 中调整。
"""
import json
from _common import prepare
from plc.variable_map import load_variable_map
from plc.writer import PLCWriter


def main() -> int:
    """打印映射缺失、计划数值和编码后的 REAL；不创建通信客户端。"""
    _, config, logger = prepare('强制离线写计划，不会连接 PLC')
    writer = PLCWriter(None, config, load_variable_map())
    plan = writer.preview('lift_right_set_speed', config['legacy']['demo_speed'])
    logger.info('%s', json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
