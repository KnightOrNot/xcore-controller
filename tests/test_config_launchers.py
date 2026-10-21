import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def controller(tmp_path):
    root = tmp_path / "controller with spaces"
    source = Path(__file__).resolve().parents[1]
    for directory in ("scripts", "tools", "config", "xcore-sdk-python/scripts"):
        (root / directory).mkdir(parents=True)
    for name in ("start_camera.sh", "start_gello_follow.sh", "start_gripper.sh"):
        shutil.copy(source / "scripts" / name, root / "scripts" / name)
    shutil.copy(source / "tools/config_defaults.py", root / "tools")
    config = root / "config/default.toml"
    config.write_text('[camera]\nsnapshot_dir = "images with spaces"\n')
    camera = root / "camera-realsense-d435i"
    (camera / ".venv/bin").mkdir(parents=True)
    (camera / "pyproject.toml").touch()
    executable = camera / ".venv/bin/camera-realsense-d435i"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json,os,pathlib,sys\n"
        "args=sys.argv[1:]\n"
        "with open(os.environ['CALLS'],'a') as f: f.write(json.dumps(args)+'\\n')\n"
        "if args[0]=='snapshot':\n"
        "    pathlib.Path(args[args.index('--output')+1]).mkdir(parents=True)\n"
    )
    executable.chmod(0o755)
    follow = root / "xcore-sdk-python/scripts/start_gello_follow.sh"
    follow.write_text('#!/bin/sh\nexec "$FAKE_CAMERA" "$@"\n')
    sdk_python = root / "xcore-sdk-python/.venv/bin/python"
    sdk_python.parent.mkdir(parents=True)
    sdk_python.symlink_to(sys.executable)
    log = root / "calls.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith("XCORE_")}
    env.update(CALLS=str(log), FAKE_CAMERA=str(executable))
    return root, config, env, log


def invoke(controller, script, *arguments):
    root, _, env, _ = controller
    return subprocess.run(
        ["bash", str(root / "scripts" / script), *arguments],
        cwd=root.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_repeated_snapshots_create_distinct_directories_for_each_camera(controller):
    root, _, _, log = controller
    for _ in range(2):
        result = invoke(controller, "start_camera.sh", "snapshot")
        assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    paths = [Path(args[args.index("--output") + 1]) for args in calls]
    assert len(set(paths)) == 4
    assert all(path.is_dir() for path in paths)
    assert {path.parent for path in paths} == {
        root / "images with spaces/cam1",
        root / "images with spaces/cam2",
    }


def test_follow_receives_configured_gripper_port_and_cli_override(controller):
    _, config, _, log = controller
    config.write_text("[remote]\ngripper_port = 6015\n")
    result = invoke(controller, "start_gello_follow.sh", "--gripper-port", "7015")
    assert result.returncode == 0, result.stderr
    args = json.loads(log.read_text())
    ports = [args[i + 1] for i, value in enumerate(args) if value == "--gripper-port"]
    assert ports == ["6015", "7015"]


def test_invalid_gripper_port_rejected_before_any_ssh(controller):
    root, config, env, log = controller
    config.write_text('[remote]\ngripper_port = "bad"\n')
    # Any attempt to reach SSH would fail the test instead of touching a device.
    binaries = root / "bin"
    binaries.mkdir()
    ssh = binaries / "ssh"
    ssh.write_text('#!/bin/sh\necho ssh >> "$CALLS"\nexit 99\n')
    ssh.chmod(0o755)
    env["PATH"] = str(binaries) + os.pathsep + os.environ["PATH"]
    result = invoke(controller, "start_gripper.sh")
    assert result.returncode != 0
    assert "remote.gripper_port" in result.stderr
    assert not log.exists()


def test_missing_defaults_do_not_silently_start_with_fallback(controller):
    _, config, _, log = controller
    config.unlink()
    result = invoke(controller, "start_gripper.sh")
    assert result.returncode != 0
    assert "读取 config/default.toml 失败" in result.stderr
    assert not log.exists()
