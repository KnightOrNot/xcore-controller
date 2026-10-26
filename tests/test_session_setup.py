import time
from types import SimpleNamespace

import pytest

from tools.config_defaults import load
from xcore_controller import session_setup as setup


@pytest.fixture
def config():
    return load().data


def healthy_controller():
    return {
        "role": "remote",
        "simulated": False,
        "motion_capable": True,
        "motion": {
            "state": "idle",
            "armed": False,
            "kinematics": "vendor",
            "gripper_enabled": True,
        },
        "recording": {"session": None, "active_episode": None},
    }


@pytest.mark.parametrize("issue", ["armed", "session", "simulated", "cleanup"])
def test_controller_readiness_rejects_busy_or_wrong_roles(config, monkeypatch, issue):
    state = healthy_controller()
    if issue == "armed":
        state["motion"]["armed"] = True
    elif issue == "session":
        state["recording"]["session"] = "someone-else"
    elif issue == "simulated":
        state["simulated"] = True
    else:
        state["motion"]["cleanup_fault"] = "scheduler did not stop"
    monkeypatch.setattr(setup, "get", lambda url: state)
    with pytest.raises(RuntimeError):
        setup.controller(config)


def test_leader_check_rejects_stale_packets(config, monkeypatch):
    packet = dict(
        version=1,
        instance="test",
        ticks=[0] * 7,
        source_monotonic_ns=time.monotonic_ns() - 2_000_000_000,
    )
    monkeypatch.setattr(setup, "get", lambda url: packet)
    with pytest.raises(RuntimeError, match="stale"):
        setup.leader(config)
    packet["source_monotonic_ns"] = time.monotonic_ns()
    assert setup.leader(config)["ready"]


def test_reused_dataset_proxy_restarts_stopped_upstream(config, monkeypatch):
    calls = []

    def invoke(args, **kwargs):
        calls.append(args)
        assert args[-1] == "systemctl --user start xcore-dataset.service"

    def read(url):
        assert calls, "must start the remote unit even when local proxy already exists"
        assert url.endswith("/api/datasets")
        return {"datasets": ["session/rev-0001"]}

    monkeypatch.setattr(setup.subprocess, "run", invoke)
    monkeypatch.setattr(setup, "get", read)
    assert setup.dataset(config)["ready"] is True
    assert len(calls) == 1


def test_gripper_activation_only_when_explicitly_requested(config, monkeypatch):
    from xcore_sdk_python import gripper_follow

    commands, checked = [], []
    state = dict(streaming=True, status_code=0, position_raw=3, moving=False)

    class Client:
        def __init__(self, *args):
            pass

        def request(self, command, **data):
            commands.append(command)
            if command == "activate":
                state["status_code"] = 49
            return dict(state)

        def check(self):
            assert state["status_code"] == 49
            return dict(state)

    monkeypatch.setattr(gripper_follow, "GripperFollowClient", Client)
    monkeypatch.setattr(
        setup.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(setup, "controller", lambda c: checked.append(True))
    assert setup.gripper(config)["activation_required"]
    assert commands == ["follow_status"] and checked == []
    assert setup.gripper(config, activate=True)["activated"]
    assert commands.count("activate") == 1 and checked == [True]
    setup.gripper(config, activate=True)
    assert commands.count("activate") == 1  # Already active: do not reinitialize.


def test_camera_setup_uses_configured_ports_and_verifies_recording(
    config, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setenv("XCORE_SESSION_LOG_DIR", str(tmp_path))

    def invoke(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="camera ready", stderr="")

    monkeypatch.setattr(setup.subprocess, "run", invoke)
    state = dict(
        service="camera-realsense-d435i",
        state="streaming",
        sequence=42,
        frame_age_s=0.01,
        recording={"configured": True},
    )
    monkeypatch.setattr(setup, "get", lambda url: state)
    assert setup.cameras(config)["count"] == 2
    assert [c[c.index("--camera") + 1] for c in calls] == ["cam1", "cam2"]
    assert [c[c.index("--remote-port") + 1] for c in calls] == ["8086", "8087"]
    state["recording"]["state"] = "recording"
    with pytest.raises(RuntimeError, match="already recording"):
        setup.cameras(config)
