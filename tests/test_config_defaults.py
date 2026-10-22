from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "config_defaults.py"


def run(
    *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )


def test_defaults_are_loaded() -> None:
    result = run("--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["robot"]["ip"] == "192.168.2.160"
    assert data["robot"]["return_mode"] == "zero"
    assert data["remote"]["gripper_host"] == "192.168.2.225"
    assert data["recording"]["dataset_fps"] == 30
    assert data["camera"]["snapshot_dir"] == "captures"


def test_get_and_unknown_key() -> None:
    assert run("--get", "remote.gripper_port").stdout.strip() == "5005"
    missing = run("--get", "robot.nope")
    assert missing.returncode == 2
    assert "unknown configuration key" in missing.stderr


def test_shell_does_not_override_existing_environment() -> None:
    result = run("--shell", env={"XCORE_GRIPPER_HOST": "10.0.0.9"})
    assert result.returncode == 0, result.stderr
    assert "XCORE_GRIPPER_HOST" not in result.stdout
    assert "XCORE_ROBOT_IP=192.168.2.160" in result.stdout
    assert "export XCORE_ROBOT_IP" in result.stdout


def test_invalid_environment_rejected_before_shell_actions():
    result = run("--shell", env={"XCORE_GRIPPER_PORT": "bad"})
    assert result.returncode == 2
    assert not result.stdout


def test_unknown_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("[nope]\nx = 1\n")
    result = run("--config", str(path), "--json")
    assert result.returncode == 2
    assert "unknown configuration sections" in result.stderr


def test_cli_override_file(tmp_path: Path) -> None:
    path = tmp_path / "experiment.toml"
    path.write_text("[robot]\nfollow_max_speed_deg = 20\n")
    result = run("--config", str(path), "--get", "robot.follow_max_speed_deg")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "20"


def test_environment_can_select_config_for_tool(tmp_path: Path) -> None:
    path = tmp_path / "experiment.toml"
    path.write_text("[remote]\ngripper_port = 6015\n")
    result = run("--get", "remote.gripper_port", env={"XCORE_CONFIG": str(path)})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "6015"


@pytest.mark.parametrize(
    "text",
    [
        '[remote]\ngripper_port = "bad"\n',
        "[remote]\ngripper_port = true\n",
        "[remote]\ngripper_port = 65536\n",
        "[robot]\nprepare_speed = nan\n",
        '[robot]\nreturn_mode = "bad"\n',
        '[robot]\nreturn_mode = "saved"\n',
        "[timeouts]\ngripper_ready_s = inf\n",
        "[timeouts]\nssh_connect_s = 0\n",
        "[recording]\ndataset_fps = true\n",
        "[camera]\nsnapshot_dir = []\n",
    ],
)
def test_invalid_defaults_are_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(text)
    result = run("--config", str(path), "--shell")
    assert result.returncode == 2
    assert not result.stdout
