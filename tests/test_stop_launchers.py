from __future__ import annotations

import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def controller(tmp_path):
    root = tmp_path / "controller with spaces"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "scripts"
    for name in ("stop_gripper.sh", "stop_camera.sh"):
        shutil.copy(source / name, scripts)
    (root / "xcore-sdk-python").mkdir()
    binaries = root / "bin"
    binaries.mkdir()
    log = root / "calls.jsonl"
    ssh = binaries / "ssh"
    ssh.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "with open(os.environ['STOP_CALLS'],'a') as f:\n"
        "    f.write(json.dumps({'command':'ssh','args':sys.argv[1:]})+'\\n')\n"
        "sys.exit(255 if os.environ.get('FAIL_SSH') else 0)\n"
    )
    ssh.chmod(0o755)
    # Only record tunnel cleanup; never connect to a real server during tests.
    (scripts / "start_camera.sh").write_text(
        "#!/usr/bin/env bash\nexec "
        + shlex.quote(sys.executable)
        + " -c "
        + shlex.quote(
            "import os,sys,json; "
            "open(os.environ['STOP_CALLS'],'a').write("
            "json.dumps({'command':'cleanup','args':sys.argv[1:]})+'\\n')"
        )
        + ' "$@"\n'
    )
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "STOP_CALLS": str(log),
    }
    for name in (
        "XCORE_GRIPPER_HOST",
        "XCORE_GRIPPER_SSH_USER",
        "XCORE_CAMERA_SSH_TARGET",
    ):
        env.pop(name, None)
    return root, env, log


def run(controller, name, options=()):
    root, env, log = controller
    result = subprocess.run(
        ["bash", str(root / "scripts" / name), *options],
        env=env,
        cwd=root.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    calls = (
        [json.loads(line) for line in log.read_text().splitlines()]
        if log.exists()
        else []
    )
    return result, calls


def test_gripper_stop_holds_same_lock_as_follow(controller):
    root, _, _ = controller
    with (root / "xcore-sdk-python/.follow.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, calls = run(controller, "stop_gripper.sh")
    assert result.returncode != 0
    assert "退出返回任务" in result.stderr
    assert calls == []


def test_idle_gripper_stop_routes_only_to_remote_service(controller):
    result, calls = run(
        controller,
        "stop_gripper.sh",
        ["--ssh-user", "operator", "--gripper-host", "192.168.2.226"],
    )
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    assert calls[0]["args"][-2] == "operator@192.168.2.226"
    assert "stop xcore-gripper-follow.service" in calls[0]["args"][-1]


def test_camera_stop_both_and_cleanup_without_start(controller):
    result, calls = run(controller, "stop_camera.sh")
    assert result.returncode == 0, result.stderr
    assert [c["command"] for c in calls] == ["ssh", "cleanup"]
    command = calls[0]["args"][-1]
    assert (
        "stop camera-realsense-d435i@cam1.service camera-realsense-d435i@cam2.service"
        in command
    )
    assert "gripper" not in command
    assert calls[1]["args"] == [
        "disconnect",
        "--camera",
        "all",
        "--ssh-target",
        "rokae@192.168.2.225",
    ]


def test_camera_stop_single_instance_with_custom_tunnel(controller):
    result, calls = run(
        controller,
        "stop_camera.sh",
        [
            "--camera",
            "cam2",
            "--ssh-target",
            "operator@host.local",
            "--local-port",
            "18087",
            "--remote-port",
            "8087",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "cam1.service" not in calls[0]["args"][-1]
    assert "cam2.service" in calls[0]["args"][-1]
    assert calls[1]["args"][-4:] == ["--local-port", "18087", "--remote-port", "8087"]


def test_failed_remote_stop_preserves_tunnel(controller):
    _, env, _ = controller
    env["FAIL_SSH"] = "1"
    result, calls = run(controller, "stop_camera.sh")
    assert result.returncode != 0
    assert [c["command"] for c in calls] == ["ssh"]


@pytest.mark.parametrize(
    "options",
    [
        ["--camera", "other"],
        ["--local-port", "18086"],
        ["--camera", "cam1", "--local-port", "65536"],
        ["--ssh-target", "user@host;touch /tmp/unwanted"],
    ],
)
def test_invalid_camera_stop_never_sends_remote_command(controller, options):
    result, calls = run(controller, "stop_camera.sh", options)
    assert result.returncode != 0
    assert calls == []
