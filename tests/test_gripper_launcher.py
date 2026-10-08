from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "controller with spaces"
    root.mkdir()
    source = Path(__file__).resolve().parents[1] / "start_gripper.sh"
    shutil.copy(source, root)
    calls = root / "calls.jsonl"
    binaries = root / "bin"
    binaries.mkdir()

    def stub(path, command):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"#!{sys.executable}\n"
            "import json,os,sys\n"
            "with open(os.environ['CALLS'],'a') as f:\n"
            f"    f.write(json.dumps({{'command':{command!r},'args':sys.argv[1:]}})+'\\n')\n"
            "print('fake service ready')\n"
        )
        path.chmod(0o755)

    stub(binaries / "ssh", "ssh")
    stub(root / "xcore-sdk-python/.venv/bin/python", "check")
    # The local launcher uses bash explicitly, so the local stub is a shell shim.
    local = root / "xcore-gripper-2F85/run_gripper.sh"
    local.parent.mkdir(parents=True)
    local.write_text(
        "#!/usr/bin/env bash\nexec " + shlex.quote(str(root / "bin/local")) + ' "$@"\n'
    )
    stub(binaries / "local", "local")
    gello = root / "gello"
    gello.touch()
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "CALLS": str(calls),
    }
    for name in ("XCORE_GRIPPER_HOST", "XCORE_GRIPPER_SSH_USER", "GRIPPER_SERIAL_PORT"):
        env.pop(name, None)
    env["XCORE_GELLO_PORT"] = str(gello)
    return root, env, calls


def run(launcher, options):
    root, env, path = launcher
    result = subprocess.run(
        ["bash", str(root / "start_gripper.sh"), *options],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    calls = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    return result, calls


@pytest.mark.parametrize(
    "options", [[], ["--status"], ["--restart"], ["--reset-stream"]]
)
def test_remote_entry_never_launches_local_serial_server(launcher, options):
    result, calls = run(launcher, options)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "local" not in [call["command"] for call in calls]
    assert calls[-1]["command"] == "check"
    assert calls[-1]["args"][1] == "192.168.2.225"
    assert calls[-1]["args"][2] == ("true" if "--reset-stream" in options else "false")
    if options == ["--status"]:
        assert len(calls) == 1
    else:
        assert calls[0]["command"] == "ssh"
        assert calls[0]["args"][-2] == "rokae@192.168.2.225"


def test_explicit_local_gripper_port_is_forwarded(launcher):
    root, _, _ = launcher
    serial = root / "actual gripper"
    serial.touch()
    result, calls = run(
        launcher, ["--local", "--serial-port", str(serial), "--no-activate"]
    )
    assert result.returncode == 0, result.stderr
    assert calls == [
        {"command": "local", "args": ["--serial-port", str(serial), "--no-activate"]}
    ]


@pytest.mark.parametrize("alias", [False, True])
def test_gello_port_and_alias_rejected_before_any_service_start(launcher, alias):
    root, _, _ = launcher
    serial = root / "gello"
    if alias:
        serial = root / "alias"
        serial.symlink_to(root / "gello")
    result, calls = run(launcher, ["--serial-port", str(serial)])
    assert result.returncode != 0
    assert "GELLO" in result.stderr
    assert calls == []


def test_local_mode_requires_an_explicit_port(launcher):
    result, calls = run(launcher, ["--local"])
    assert result.returncode != 0
    assert "必须指定 --serial-port" in result.stderr
    assert calls == []
