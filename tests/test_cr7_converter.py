from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from lerobot_converter.converter import ConversionError
from lerobot_converter.converter import convert_session as original_convert_session

from tools.convert_cr7 import convert_session


def _frame(sequence: int, timestamp_ns: int) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "command_time_ns": timestamp_ns - 1,
        "observation_time_ns": timestamp_ns,
        "wall_time_ns": timestamp_ns + 1,
        "control_period_ns": 20_000_000,
        "action": [0.0] * 6 + [1.0],
        "joint_positions": [0.1] * 6 + [0.5],
        "joint_velocities": [0.0] * 7,
        "ee_pos_quat": [0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 1.0],
        "gripper_position": 0.5,
    }


def _session(tmp_path: Path, count: int = 6) -> Path:
    session = tmp_path / "session_20260101_000000"
    episodes = session / "episodes"
    episodes.mkdir(parents=True)
    manifest = {
        "format": "piper_x_gello_raw",
        "format_version": 1,
        "clock": "time.monotonic_ns",
        "robot_type": "piper_x",
        "control_hz": 50.0,
        "task": "pick object",
        "joint_units": "rad",
        "velocity_units": "rad/s",
        "position_units": "m",
        "gripper_range": [0.0, 1.0],
        "quaternion_order": "xyzw",
        "joint_names": [f"joint_{index}" for index in range(1, 7)] + ["gripper"],
    }
    (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    rows = [_frame(index, 1_000_000_000 + index * 20_000_000) for index in range(count)]
    (episodes / "episode_000000.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return session


class FakeDataset:
    def __init__(self, root: Path) -> None:
        root.mkdir()
        self.current: list[dict[str, Any]] = []
        self.episodes: list[list[dict[str, Any]]] = []
        self.finalized = False

    def add_frame(self, frame: dict[str, Any]) -> None:
        self.current.append(frame)

    def save_episode(self) -> None:
        self.episodes.append(self.current)
        self.current = []

    def finalize(self) -> None:
        self.finalized = True


def _cr7_session(tmp_path: Path) -> Path:
    session = _session(tmp_path, count=21)
    path = session / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(format="xcore_cr7_gello_raw", robot_type="xmate_cr7")
    path.write_text(json.dumps(manifest))
    rows = []
    for index in range(21):
        timestamp = 1_000_000_000 + index * 20_000_000
        row = _frame(index, timestamp)
        del row["joint_velocities"], row["ee_pos_quat"]
        row["arm_feedback_time_ns"] = 1_000_000_000 + (index // 2) * 40_000_000
        row["gripper_feedback_time_ns"] = 1_000_000_000 + (index // 10) * 200_000_000
        rows.append(row)
    (session / "episodes/episode_000000.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    return session


def test_cr7_conversion_keeps_measured_seven_channels_without_fake_features(tmp_path):
    session = _cr7_session(tmp_path)
    factory_args = {}
    datasets = []

    def factory(**kwargs):
        factory_args.update(kwargs)
        dataset = FakeDataset(kwargs["root"])
        datasets.append(dataset)
        return dataset

    report = convert_session(
        session, tmp_path / "dataset", repo_id="local/cr7", dataset_factory=factory
    )
    assert factory_args["robot_type"] == "xmate_cr7"
    assert set(factory_args["features"]) == {"observation.state", "action"}
    assert datasets[0].episodes[0][0]["observation.state"][-1] == pytest.approx(0.5)
    assert datasets[0].episodes[0][0]["action"][-1] == pytest.approx(1.0)
    assert report.episodes[0].actual_sample_hz == pytest.approx(50)
    assert report.episodes[0].arm_feedback_hz == pytest.approx(25)
    assert report.episodes[0].gripper_feedback_hz == pytest.approx(5)
    assert report.episodes[0].max_gripper_feedback_age_ms == pytest.approx(180)


def test_cr7_missing_feedback_timestamp_is_rejected_before_output_creation(tmp_path):
    session = _cr7_session(tmp_path)
    path = session / "episodes/episode_000000.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    del rows[0]["gripper_feedback_time_ns"]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    output = tmp_path / "dataset"
    with pytest.raises(ConversionError, match="gripper_feedback_time_ns"):
        convert_session(
            session, output, repo_id="local/cr7", dataset_factory=FakeDataset
        )
    assert not output.exists()


def test_robot_identity_must_match_raw_profile(tmp_path):
    session = _cr7_session(tmp_path)
    path = session / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["robot_type"] = "piper_x"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ConversionError, match="robot_type"):
        convert_session(session, tmp_path / "dataset", repo_id="local/cr7")


def test_original_piper_converter_keeps_its_original_format_contract(tmp_path):
    session = _cr7_session(tmp_path)
    with pytest.raises(ConversionError, match="format.*piper_x_gello_raw"):
        original_convert_session(session, tmp_path / "dataset", repo_id="local/cr7")
