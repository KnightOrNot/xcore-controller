#!/usr/bin/env python3
"""Read ``config/default.toml`` for the controller shell entry points.

The controller keeps its defaults in one TOML file so scripts do not grow
duplicated literals. Environment variables that are already set win over the
file, matching the previous ``${XCORE_*:-default}`` behaviour.

Usage::

    eval "$(tools/config_defaults.py --shell)"
    tools/config_defaults.py --get remote.gripper_host
    tools/config_defaults.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/default.toml"

SECTIONS = {
    "robot": {
        "ip": "XCORE_ROBOT_IP",
        "follow_max_speed_deg": "XCORE_FOLLOW_MAX_SPEED_DEG",
        "prepare_speed": "XCORE_PREPARE_SPEED",
        "return_mode": "XCORE_RETURN_MODE",
    },
    "gello": {"port": "XCORE_GELLO_PORT"},
    "remote": {
        "gripper_host": "XCORE_GRIPPER_HOST",
        "gripper_ssh_user": "XCORE_GRIPPER_SSH_USER",
        "gripper_port": "XCORE_GRIPPER_PORT",
        "camera_ssh_target": "XCORE_CAMERA_SSH_TARGET",
    },
    "camera": {
        "snapshot_dir": "XCORE_CAMERA_SNAPSHOT_DIR",
        "cam1_url": "XCORE_CAM1_URL",
        "cam2_url": "XCORE_CAM2_URL",
    },
    "recording": {
        "raw_data_root": "XCORE_RAW_DATA_ROOT",
        "lerobot_data_root": "XCORE_LEROBOT_DATA_ROOT",
        "dataset_fps": "XCORE_DATASET_FPS",
        "raw_fps": "XCORE_RAW_FPS",
        "camera_max_frame_age_s": "XCORE_CAMERA_MAX_FRAME_AGE_S",
        "convert": "XCORE_CONVERT",
        "task": "XCORE_TASK",
    },
    "paths": {
        "sdk_project": "XCORE_SDK_PROJECT",
        "gello_project": "XCORE_GELLO_PROJECT",
        "gripper_project": "XCORE_GRIPPER_PROJECT",
        "converter_project": "XCORE_CONVERTER_PROJECT",
        "camera_project": "XCORE_CAMERA_PROJECT",
    },
    "timeouts": {
        "ssh_connect_s": "XCORE_SSH_CONNECT_TIMEOUT",
        "gripper_ready_s": "XCORE_GRIPPER_READY_TIMEOUT",
    },
    "roles": {
        "bind_host": "XCORE_ROLE_BIND_HOST",
        "gello_port": "XCORE_GELLO_SERVICE_PORT",
        "controller_port": "XCORE_CONTROLLER_SERVICE_PORT",
        "leader_poll_hz": "XCORE_LEADER_POLL_HZ",
        "leader_timeout_s": "XCORE_LEADER_TIMEOUT_S",
        "remote_local_ip": "XCORE_REMOTE_LOCAL_IP",
        "remote_project": "XCORE_REMOTE_PROJECT",
        "remote_python": "XCORE_REMOTE_PYTHON",
        "remote_dataset_python": "XCORE_REMOTE_DATASET_PYTHON",
        "remote_data_root": "XCORE_REMOTE_DATA_ROOT",
        "dataset_port": "XCORE_DATASET_SERVICE_PORT",
    },
}


@dataclass(frozen=True)
class Values:
    data: dict[str, dict[str, Any]]
    path: Path

    def get(self, dotted: str) -> Any:
        section, _, key = dotted.partition(".")
        if not key:
            raise KeyError(f"expected section.key, got {dotted!r}")
        if section not in self.data or key not in self.data[section]:
            raise KeyError(f"unknown configuration key: {dotted}")
        return self.data[section][key]

    def with_environment(self) -> Values:
        effective = {name: dict(values) for name, values in self.data.items()}
        for section, keys in SECTIONS.items():
            for key, variable in keys.items():
                if variable not in os.environ:
                    continue
                value = os.environ[variable]
                kind = type(_builtin(section, key))
                if kind is bool:
                    if value not in ("true", "false"):
                        raise ValueError(f"{variable} must be true or false")
                    parsed = value == "true"
                elif kind is int:
                    parsed = (
                        float(value)
                        if section == "robot"
                        or (section, key) == ("timeouts", "gripper_ready_s")
                        else int(value)
                    )
                elif kind is float:
                    parsed = float(value)
                else:
                    parsed = value
                effective[section][key] = parsed
        result = Values(effective, self.path)
        validate(result)
        return result

    def shell(self) -> str:
        self.with_environment()
        lines = []
        for section, keys in SECTIONS.items():
            for key, variable in keys.items():
                if variable in os.environ:
                    continue
                value = self.data[section][key]
                if isinstance(value, bool):
                    value = "true" if value else "false"
                lines.append(f"{variable}={shlex.quote(str(value))}")
                lines.append(f"export {variable}")
        return "\n".join(lines)


def load(path: Path | None = None) -> Values:
    selected = Path(path or os.environ.get("XCORE_CONFIG") or DEFAULT_CONFIG)
    with selected.open("rb") as stream:
        raw = tomllib.load(stream)
    unknown = raw.keys() - SECTIONS.keys()
    if unknown:
        raise ValueError(f"unknown configuration sections: {sorted(unknown)}")
    data: dict[str, dict[str, Any]] = {}
    for section, keys in SECTIONS.items():
        values = raw.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"{section} must be a TOML table")
        unknown = values.keys() - keys.keys()
        if unknown:
            raise ValueError(f"unknown {section} options: {sorted(unknown)}")
        data[section] = {key: values.get(key, _builtin(section, key)) for key in keys}
    result = Values(data=data, path=selected)
    validate(result)
    return result


def _builtin(section: str, key: str) -> Any:
    builtin = {
        ("robot", "ip"): "192.168.2.160",
        ("robot", "follow_max_speed_deg"): 75,
        ("robot", "prepare_speed"): 4000,
        ("robot", "return_mode"): "zero",
        ("gello", "port"): "",
        ("remote", "gripper_host"): "192.168.2.225",
        ("remote", "gripper_ssh_user"): "rokae",
        ("remote", "gripper_port"): 5005,
        ("remote", "camera_ssh_target"): "rokae@192.168.2.225",
        ("camera", "snapshot_dir"): "captures",
        ("camera", "cam1_url"): "http://127.0.0.1:8086",
        ("camera", "cam2_url"): "http://127.0.0.1:8087",
        ("recording", "raw_data_root"): "data/raw",
        ("recording", "lerobot_data_root"): "data/lerobot",
        ("recording", "dataset_fps"): 30,
        ("recording", "raw_fps"): 15,
        ("recording", "camera_max_frame_age_s"): 0.5,
        ("recording", "convert"): True,
        ("recording", "task"): "CR7 GELLO teleoperation",
        ("paths", "sdk_project"): "xcore-sdk-python",
        ("paths", "gello_project"): "xcore-gello-software",
        ("paths", "gripper_project"): "xcore-gripper-2F85",
        ("paths", "converter_project"): "lerobot-converter",
        ("paths", "camera_project"): "camera-realsense-d435i",
        ("timeouts", "ssh_connect_s"): 5,
        ("timeouts", "gripper_ready_s"): 15,
        ("roles", "bind_host"): "127.0.0.1",
        ("roles", "gello_port"): 9011,
        ("roles", "controller_port"): 9012,
        ("roles", "leader_poll_hz"): 25,
        ("roles", "leader_timeout_s"): 0.5,
        ("roles", "remote_local_ip"): "192.168.2.225",
        ("roles", "remote_project"): "project/xcore-controller",
        (
            "roles",
            "remote_python",
        ): "project/xcore-runtime/cpython-3.11.16-linux-x86_64-gnu/bin/python3.11",
        (
            "roles",
            "remote_dataset_python",
        ): "project/xcore-runtime/dataset-venv/bin/python",
        ("roles", "remote_data_root"): "project/xcore-data",
        ("roles", "dataset_port"): 8090,
    }
    return builtin[(section, key)]


def validate(values: Values) -> None:
    numeric = {
        ("robot", "follow_max_speed_deg"),
        ("robot", "prepare_speed"),
        ("timeouts", "gripper_ready_s"),
        ("roles", "leader_timeout_s"),
        ("recording", "raw_fps"),
        ("recording", "camera_max_frame_age_s"),
    }
    for section, keys in SECTIONS.items():
        for key in keys:
            value = values.get(f"{section}.{key}")
            expected = type(_builtin(section, key))
            if (section, key) in numeric:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    raise ValueError(f"{section}.{key} must be positive and finite")
            elif type(value) is not expected:
                raise ValueError(f"{section}.{key} must be {expected.__name__}")
            elif (
                expected is str
                and not value.strip()
                and (section, key) != ("gello", "port")
            ):
                raise ValueError(f"{section}.{key} must be non-empty")
    for key in ("follow_max_speed_deg", "prepare_speed"):
        value = values.get(f"robot.{key}")
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"robot.{key} must be positive")
    if values.get("robot.follow_max_speed_deg") > 75:
        raise ValueError("robot.follow_max_speed_deg is limited to 75 deg/s")
    mode = values.get("robot.return_mode")
    if mode not in ("start", "zero", "none"):
        raise ValueError("robot.return_mode must be start, zero or none")
    if not 5 <= values.get("robot.prepare_speed") <= 4000:
        raise ValueError("robot.prepare_speed must be in 5..4000 mm/s")
    if not 1 <= values.get("remote.gripper_port") <= 65535:
        raise ValueError("remote.gripper_port must be in 1..65535")
    if values.get("timeouts.ssh_connect_s") <= 0:
        raise ValueError("timeouts.ssh_connect_s must be a positive integer")
    if values.get("roles.bind_host") not in ("127.0.0.1", "::1"):
        raise ValueError("role services must bind loopback; use SSH forwarding")
    for key in ("gello_port", "controller_port", "dataset_port"):
        if not 1 <= values.get("roles." + key) <= 65535:
            raise ValueError("invalid role service port")
    if not 1 <= values.get("roles.leader_poll_hz") <= 100:
        raise ValueError("leader_poll_hz must be in 1..100")
    fps = values.get("recording.dataset_fps")
    if not isinstance(fps, int) or fps <= 0:
        raise ValueError("recording.dataset_fps must be a positive integer")
    raw_fps = values.get("recording.raw_fps")
    if not isinstance(raw_fps, int) or not 1 <= raw_fps <= 60:
        raise ValueError("recording.raw_fps must be an integer in 1..60")
    for key in ("cam1_url", "cam2_url"):
        if not values.get("camera." + key).startswith("http://127.0.0.1:"):
            raise ValueError(f"camera.{key} must use remote loopback HTTP")
    if not isinstance(values.get("recording.convert"), bool):
        raise ValueError("recording.convert must be a boolean")
    if not str(values.get("recording.task")).strip():
        raise ValueError("recording.task must be non-empty")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="TOML defaults file")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--shell", action="store_true", help="emit shell assignments")
    output.add_argument("--json", action="store_true", help="emit JSON")
    output.add_argument("--get", metavar="SECTION.KEY", help="print one value")
    arguments = parser.parse_args(argv)
    try:
        values = load(arguments.config)
    except (OSError, ValueError, KeyError) as exc:
        print(f"config_defaults: {exc}", file=sys.stderr)
        return 2
    if arguments.shell:
        try:
            print(values.shell())
        except ValueError as exc:
            print(f"config_defaults: {exc}", file=sys.stderr)
            return 2
    elif arguments.json:
        print(json.dumps(values.data, ensure_ascii=False, indent=2, sort_keys=True))
    elif arguments.get:
        try:
            print(values.get(arguments.get))
        except KeyError as exc:
            print(f"config_defaults: {exc}", file=sys.stderr)
            return 2
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
