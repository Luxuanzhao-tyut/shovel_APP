"""
建立中文控制台和文件日志；输入配置与目录，输出 logging.Logger。
日志不触发 PLC 通信，使用新文件保留历史输出；调整日志格式时修改。
"""
import logging
from datetime import datetime
from pathlib import Path


def setup_logger(config: dict, directory: Path) -> logging.Logger:
    """按配置启用输出，重复调用先关闭旧处理器以免日志重复。"""
    logger = logging.getLogger('shovel_plc')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    handlers = []
    if config['logging']['console']:
        handlers.append(logging.StreamHandler())
    if config['logging']['save_to_file']:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / datetime.now().strftime('plc_%Y%m%d_%H%M%S_%f.log')
        handlers.append(logging.FileHandler(path, mode='x', encoding='utf-8'))
    for handler in handlers:
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
    return logger
