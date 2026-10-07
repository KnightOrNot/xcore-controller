"""Separate CR7/Robotiq adapter; the original PiPER-X converter is unchanged.

Run with ``lerobot-converter/.venv/bin/python tools/convert_cr7.py SESSION OUTPUT --fps 30``.
This module reuses the existing resampler, feature builder and LeRobot writer
factory, while validating the CR7 format without inventing missing sensor data.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from lerobot_converter.converter import (
    _INTEGER_FIELDS,
    ConversionError,
    ConversionReport,
    EpisodeQuality,
    PreparedEpisode,
    _default_dataset_factory,
    _features,
    _finite_vector,
    _nearest_indices,
)


@dataclass(frozen=True)
class CR7EpisodeQuality(EpisodeQuality):
    arm_feedback_hz: float
    gripper_feedback_hz: float
    max_arm_feedback_age_ms: float
    max_gripper_feedback_age_ms: float


def _manifest(session: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((session / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConversionError(f"Invalid CR7 manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ConversionError("CR7 manifest must be an object")
    for field, expected in {
        "format": "xcore_cr7_gello_raw",
        "format_version": 1,
        "robot_type": "xmate_cr7",
        "clock": "time.monotonic_ns",
        "joint_units": "rad",
        "gripper_range": [0.0, 1.0],
    }.items():
        if manifest.get(field) != expected:
            raise ConversionError(f"CR7 manifest {field} must be {expected!r}")
    task = manifest.get("task")
    if not isinstance(task, str) or not task.strip():
        raise ConversionError("CR7 task must be non-empty")
    hz = manifest.get("control_hz")
    if (
        isinstance(hz, bool)
        or not isinstance(hz, (int, float))
        or not math.isfinite(hz)
        or hz <= 0
    ):
        raise ConversionError("CR7 control_hz must be positive and finite")
    names = manifest.get("joint_names")
    if (
        not isinstance(names, list)
        or len(names) != 7
        or not all(isinstance(name, str) and name for name in names)
    ):
        raise ConversionError("CR7 joint_names must contain seven names")
    return manifest


def _frame(value: Any, location: str, sequence: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConversionError(f"{location}: frame must be an object")
    row = dict(value)
    for field in _INTEGER_FIELDS:
        number = row.get(field)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ConversionError(f"{location}: invalid {field}")
    if row["sequence"] != sequence:
        raise ConversionError(f"{location}: expected sequence {sequence}")
    for field in ("action", "joint_positions"):
        row[field] = _finite_vector(row.get(field), 7, field, location)
        if not 0 <= row[field][-1] <= 1:
            raise ConversionError(f"{location}: {field} gripper must be in [0,1]")
    gripper = row.get("gripper_position")
    if (
        isinstance(gripper, bool)
        or not isinstance(gripper, (int, float))
        or not math.isfinite(gripper)
        or not 0 <= gripper <= 1
    ):
        raise ConversionError(f"{location}: invalid gripper_position")
    if not math.isclose(row["joint_positions"][-1], gripper, abs_tol=1e-6):
        raise ConversionError(f"{location}: inconsistent gripper feedback")
    for field in ("arm_feedback_time_ns", "gripper_feedback_time_ns"):
        timestamp = row.get(field)
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or not 0 < timestamp <= row["observation_time_ns"]
        ):
            raise ConversionError(f"{location}: invalid {field}")
    return row


def prepare_episode(path: Path, *, fps: int) -> PreparedEpisode:
    if fps <= 0:
        raise ValueError("fps must be positive")
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            location = f"{path}:{line_number}"
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ConversionError(f"{location}: invalid JSON") from exc
            rows.append(_frame(value, location, len(rows)))
    if not rows:
        raise ConversionError(f"Empty episode: {path}")
    times = [row["observation_time_ns"] for row in rows]
    intervals = [b - a for a, b in pairwise(times)]
    if any(interval <= 0 for interval in intervals):
        raise ConversionError(f"{path}: observation times must increase")
    selected, error = _nearest_indices(times, fps)
    duration = (times[-1] - times[0]) / 1e9
    sensors = {}
    for component in ("arm", "gripper"):
        field = f"{component}_feedback_time_ns"
        unique = sorted({row[field] for row in rows})
        span = (unique[-1] - unique[0]) / 1e9
        sensors[f"{component}_feedback_hz"] = (
            (len(unique) - 1) / span if span > 0 else 0.0
        )
        sensors[f"max_{component}_feedback_age_ms"] = max(
            (row["observation_time_ns"] - row[field]) / 1e6 for row in rows
        )
    quality = CR7EpisodeQuality(
        source=str(path),
        raw_samples=len(rows),
        converted_frames=len(selected),
        duration_s=duration,
        actual_sample_hz=(len(rows) - 1) / duration if duration > 0 else 0,
        average_interval_ms=sum(intervals) / len(intervals) / 1e6 if intervals else 0,
        max_interval_ms=max(intervals) / 1e6 if intervals else 0,
        missing_sequences=0,
        duplicate_sequences=0,
        dimension_errors=0,
        non_finite_errors=0,
        max_time_match_error_ms=error,
        **sensors,
    )
    return PreparedEpisode(path, tuple(rows[i] for i in selected), quality)


def convert_session(
    session: str | Path,
    output: str | Path,
    *,
    repo_id: str,
    fps: int = 30,
    dataset_factory: Any = _default_dataset_factory,
) -> ConversionReport:
    source, destination = Path(session).resolve(), Path(output).resolve()
    if destination.exists():
        raise ConversionError(f"output already exists: {destination}")
    manifest = _manifest(source)
    paths = sorted((source / "episodes").glob("episode_*.jsonl"))
    if not paths:
        raise ConversionError("no completed episodes found")
    episodes = tuple(prepare_episode(path, fps=fps) for path in paths)
    dataset = dataset_factory(
        repo_id=repo_id,
        fps=fps,
        root=destination,
        robot_type=manifest["robot_type"],
        use_videos=False,
        features=_features(
            manifest["joint_names"], include_velocity=False, include_ee_pose=False
        ),
    )
    try:
        import numpy as np

        for episode in episodes:
            for row in episode.frames:
                dataset.add_frame(
                    {
                        "observation.state": np.asarray(
                            row["joint_positions"], dtype=np.float32
                        ),
                        "action": np.asarray(row["action"], dtype=np.float32),
                        "task": manifest["task"],
                    }
                )
            dataset.save_episode()
        dataset.finalize()
    except Exception as exc:
        raise ConversionError(f"LeRobot dataset writer failed: {exc}") from exc
    qualities = tuple(episode.quality for episode in episodes)
    report = ConversionReport(
        source_session=str(source),
        output_root=str(destination),
        repo_id=repo_id,
        target_fps=fps,
        raw_samples=sum(q.raw_samples for q in qualities),
        converted_frames=sum(q.converted_frames for q in qualities),
        kept_episodes=len(episodes),
        failed_episodes=0,
        ignored_partial_episodes=len(
            list((source / "episodes").glob("episode_*.jsonl.partial"))
        ),
        episodes=qualities,
    )
    (destination / "quality_report.json").write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo-id")
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        report = convert_session(
            args.session,
            args.output,
            repo_id=args.repo_id or f"local/cr7_{args.session.name}",
            fps=args.fps,
        )
    except (ConversionError, OSError, ValueError) as exc:
        print(f"CR7 converter: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
