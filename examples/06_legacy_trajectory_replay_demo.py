"""
该算法属于速度序列开环复现，并非闭环轨迹跟踪，不建议作为最终自主控制方案。
输入三帧教学速度，输出固定周期的离线回放计划；没有 PLC 客户端、写入或自动闸控制。
该示例不是现场实测历史轨迹；研究历史 baseline 时修改输入速度点。
"""
import json
from _common import prepare
from trajectory.trajectory_point import TrajectoryPoint
from trajectory.legacy_speed_replay import build_replay_plan


def main() -> int:
    """只计算计划时间，不按墙钟执行，不调用真实或伪装为 mock 的控制接口。"""
    _, config, logger = prepare('旧开环速度复现的离线计划演示')
    speed = config['legacy']['demo_speed']
    points = [TrajectoryPoint(-speed, speed, 0.0), TrajectoryPoint(0.0, 0.0, speed), TrajectoryPoint(0.0, 0.0, 0.0)]
    for row in build_replay_plan(points, config):
        logger.info('%s', json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
