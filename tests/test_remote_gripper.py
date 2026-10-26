import math
import time
from types import SimpleNamespace

import pytest
from xcore_sdk_python.configuration import GripperConfig

from xcore_controller.gripper import RemoteGripper


class FakeFollower:
    def __init__(self, client, **kwargs):
        self.state = kwargs["initial_feedback"]
        self.targets = []
        self.closed = False
        client.follower = self

    def check(self):
        pass

    def feedback(self):
        return dict(self.state)

    def submit(self, target):
        self.targets.append(target)

    def close(self):
        self.closed = True


def test_trigger_targets_are_distinct_from_measured_closure():
    client = SimpleNamespace(check=lambda: {"position_raw": 51})
    config = GripperConfig()
    gripper = RemoteGripper(
        config,
        port=5005,
        feedback_max_age_s=0.5,
        client=client,
        follower_factory=FakeFollower,
    )
    gripper.start()
    ticks = [0] * 6 + [round(config.close_deg / 180 * 2048)]
    sample = gripper.submit(ticks)
    assert sample["closure"] == pytest.approx(0.2)
    assert sample["target_closure"] == pytest.approx(1.0, abs=0.002)
    assert len(client.follower.targets) == 1
    client.follower.state["feedback_time_ns"] = time.monotonic_ns() - 1_000_000_000
    with pytest.raises(RuntimeError, match="stale"):
        gripper.submit(ticks)
    assert len(client.follower.targets) == 1
    gripper.close()
    assert client.follower.closed


def test_real_tcp_follower_protocol_without_hardware():
    class Client:
        timeout = 0.2

        def __init__(self):
            self.commands = []

        def check(self):
            return {"position_raw": 0}

        def request(self, command, **data):
            self.commands.append((command, data))
            return {"position_raw": data.get("pos", 0)}

    client = Client()
    gripper = RemoteGripper(
        GripperConfig(hz=100),
        port=5005,
        feedback_max_age_s=0.5,
        client=client,
    )
    gripper.start()
    assert client.commands == []  # No targets on API start/arm preflight.
    sample = gripper.submit([0] * 6 + [round(174 / 180 * 2048)])
    assert 0 < sample["target_closure"] < 1
    deadline = time.monotonic() + 1
    while not client.commands and time.monotonic() < deadline:
        time.sleep(0.005)
    gripper.close()
    assert client.commands[0][0] == "set_target"
    assert math.isclose(
        client.commands[0][1]["pos"] / 255, sample["target_closure"], abs_tol=0.002
    )
    assert client.commands[-1][0] == "stop"


def test_feedback_stays_fresh_during_rt_startup_without_motion_targets():
    class Client:
        timeout = 0.1

        def __init__(self):
            self.polls = 0

        def check(self):
            self.polls += 1
            return {"position_raw": 51}

        def request(self, *args, **kwargs):
            raise AssertionError("warmup must not send motion targets")

    client = Client()
    gripper = RemoteGripper(
        GripperConfig(hz=50),
        port=5005,
        feedback_max_age_s=0.2,
        client=client,
    )
    try:
        gripper.start()
        time.sleep(0.35)  # Longer than the initial feedback validity window.
        assert gripper.feedback()["closure"] == pytest.approx(0.2)
        assert client.polls >= 2
    finally:
        gripper.close()
