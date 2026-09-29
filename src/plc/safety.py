"""兼容旧导入的安全模块。

当前真实写联锁统一实现于 :mod:`plc.live_control` 的 LiveControlManager。
保留 check_write 只用于提醒旧调用方迁移，避免旧业务代码绕开状态机直接批准写入。
"""


def check_write(*_args, **_kwargs) -> None:
    raise RuntimeError('旧 check_write 已停用；真实写必须通过 LiveControlManager')
