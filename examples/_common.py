"""
示例共享的导入和参数准备；输入命令行，输出配置/日志/路径。
不构造连接、不模拟 PLC 地址；调整示例的命令行说明时修改。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from plc.config import load_config
from utils.logger import setup_logger


def prepare(description: str, offline_available: bool = False):
    """解析参数；--offline 明确标记空状态演示，--count 适用于监控与记录。"""
    parser = argparse.ArgumentParser(description=description)
    if offline_available:
        parser.add_argument('--offline', action='store_true', help='不连接 PLC；只验证空状态/字节示例')
        parser.add_argument('--count', type=int, default=10, help='监控/记录样本数，0 表示持续到 Ctrl+C')
    args = parser.parse_args()
    if offline_available and args.count < 0:
        parser.error('--count 不能为负数')
    config = load_config()
    logger = setup_logger(config, ROOT / 'logs')
    return args, config, logger
