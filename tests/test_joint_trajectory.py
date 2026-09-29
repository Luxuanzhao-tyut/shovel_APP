from pathlib import Path

import pytest

from trajectory.joint_trajectory import JointTrajectory, JointWaypoint, load_joint_trajectory, save_joint_trajectory


def test_joint_trajectory_linear_interpolation():
    traj = JointTrajectory((
        JointWaypoint(0.0, 100.0, 200.0, 170.0),
        JointWaypoint(2.0, 200.0, 400.0, -170.0),
    ))
    p = traj.reference_at(1.0)
    assert p.lift == pytest.approx(150.0)
    assert p.push == pytest.approx(300.0)
    # 回转走最短路径：170 -> 190(=-170)，中点 180。
    assert p.swing == pytest.approx(180.0)


def test_joint_trajectory_requires_zero_start_and_increasing_time():
    with pytest.raises(ValueError):
        JointTrajectory((JointWaypoint(1, 0, 0, 0), JointWaypoint(2, 0, 0, 0))).validate()
    with pytest.raises(ValueError):
        JointTrajectory((JointWaypoint(0, 0, 0, 0), JointWaypoint(0, 1, 1, 1))).validate()


def test_joint_trajectory_csv_roundtrip(tmp_path: Path):
    traj = JointTrajectory((JointWaypoint(0, 1, 2, 3), JointWaypoint(2.5, 4, 5, 6)), 'demo')
    path = save_joint_trajectory(tmp_path / 'traj.csv', traj)
    loaded = load_joint_trajectory(path)
    assert loaded.points == traj.points
    assert loaded.duration_s == pytest.approx(2.5)
