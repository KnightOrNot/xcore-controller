import json
import math
import threading
import time

import pytest
from xcore_adapters.leader import LeaderInbox

from xcore_controller.motion import MotionSettings, MotionWorker


class Enum:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Enum) and other.name == self.name


class FakeSdk:
    class MotionControlMode:
        NrtCommandMode = Enum("nrt")

    class OperationState:
        idle = Enum("idle")

    class PowerState:
        on = Enum("on")
        off = Enum("off")


class FakeDriver:
    def __init__(self):
        self.sdk = FakeSdk()
        self.robot = object()
        self.values = [0.1] * 6
        self.moves = []
        self.mode_value = Enum("manual")
        self.power_value = Enum("off")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def close(self):
        pass

    def joints(self):
        return {"rad": list(self.values)}

    def limits(self):
        return {"enabled": True, "rad": [[-math.pi, math.pi]] * 6}

    def call(self, name, *args):
        if name == "setMotionControlMode":
            # Model the controller powering off on a control-mode transition.
            self.power_value = Enum("off")
            return None
        return {
            "operationState": Enum("idle"),
            "powerState": self.power_value,
            "operateMode": self.mode_value,
        }[name]

    def mode(self, name):
        self.mode_value = Enum(name)

    def power(self, on):
        self.power_value = Enum("on" if on else "off")

    def stop(self):
        pass

    def movej(self, target, **options):
        assert options.get("motion_mode_prepared") is True
        assert self.power_value == self.sdk.PowerState.on
        self.moves.append((list(target), options))
        self.values = list(target)
        return {"reached": True, "actual_rad": list(target)}


class FakeBot:
    instances = []

    def __init__(self, driver, settings, verbose):
        self.driver, self.settings = driver, settings
        self.targets = []
        self.closed = 0
        FakeBot.instances.append(self)

    def command_joint_state(self, target):
        self.targets.append(list(target))

    def get_joint_state(self):
        return list(self.driver.values)

    def abort_reason(self):
        return None

    def motion_active(self):
        return bool(self.targets)

    def stats(self):
        return {"cb_calls": 10 if self.targets else 0}

    def close(self):
        self.closed += 1


def ticks(radians):
    return [round(value / math.pi * 2048) for value in radians]


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for motion state")
        time.sleep(0.005)


def make_worker(
    tmp_path,
    *,
    gate_deg=17.0,
    return_mode="start",
    stale=0.2,
    gripper_factory=None,
    bot_factory=FakeBot,
):
    FakeBot.instances.clear()
    calib = tmp_path / "calib.json"
    calib.write_text(
        json.dumps({"joint_offsets": [0.0] * 6, "joint_signs": [1] * 6, "ok": True})
    )
    settings = MotionSettings(
        ip="127.0.0.1",
        calibration=str(calib),
        max_speed_deg=75,
        stale_timeout_s=stale,
        gate_deg=gate_deg,
        prepare_samples=3,
        prepare_interval_s=0.01,
        return_mode=return_mode,
    )
    inbox = LeaderInbox(1.0)
    lock = threading.RLock()
    inbox.handshake("leader")
    driver = FakeDriver()
    worker = MotionWorker(
        settings,
        inbox,
        lock,
        driver_factory=lambda: driver,
        bot_factory=bot_factory,
        gripper_factory=gripper_factory,
        verbose=False,
    )
    wait_for(lambda: worker.status()["state"] == "idle")
    return worker, inbox, driver


def send_leader(inbox, sequence, radians):
    inbox.accept(
        {
            "version": 1,
            "instance": "leader",
            "sequence": sequence,
            "source_monotonic_ns": time.monotonic_ns() + sequence,
            "ticks": ticks(radians) + [ticks([0.0])[0]],
        }
    )


def test_arm_forwards_and_disarm_stops(tmp_path):
    worker, inbox, driver = make_worker(tmp_path)
    send_leader(inbox, 0, [0.1] * 6)
    status = worker.arm()
    assert status["armed"] is True and status["state"] == "following"
    send_leader(inbox, 1, [0.12] * 6)
    bot = FakeBot.instances[-1]
    wait_for(lambda: bot.targets and bot.targets[-1][0] > 0.11)
    assert max(abs(v - 0.12) for v in bot.targets[-1]) < 1e-3
    worker.disarm()
    assert worker.status()["armed"] is False
    assert bot.closed == 1
    worker.close()


def test_arm_gate_rejects_far_leader(tmp_path):
    worker, inbox, _ = make_worker(tmp_path, gate_deg=5.0)
    send_leader(inbox, 0, [0.5] * 6)
    with pytest.raises(RuntimeError, match="exceeds gate"):
        worker.arm()
    assert worker.status()["armed"] is False
    assert not FakeBot.instances
    worker.close()


def test_arm_drives_gripper_and_records_measured_and_desired_closure(tmp_path):
    import numpy as np

    class Gripper:
        def __init__(self):
            self.targets = []
            self.closed = False

        def start(self):
            pass

        def submit(self, ticks):
            self.targets.append(ticks[6])
            return dict(self.feedback(), target_closure=0.8)

        def feedback(self):
            return {
                "closure": 0.2,
                "position_raw": 51,
                "feedback_time_ns": time.monotonic_ns(),
            }

        def close(self):
            self.closed = True

    class Kinematics:
        def state(self, joints, closure):
            return np.asarray([0, 0, 0, 1, 0, 0, 0, 1, 0, closure])

    gripper = Gripper()
    worker, inbox, _ = make_worker(tmp_path, gripper_factory=lambda: gripper)
    try:
        assert not gripper.targets
        send_leader(inbox, 0, [0.1] * 6)
        worker.arm()
        with worker._lock:
            worker._kinematics = Kinematics()
        wait_for(lambda: worker.sample() and worker.sample()["state_pose10"])
        sample = worker.sample()
        assert sample["state_pose10"][-1] == pytest.approx(0.2)
        assert sample["target_pose10"][-1] == pytest.approx(0.8)
        assert sample["gripper_position_raw"] == 51
        assert sample["gripper_enabled"] is True
        worker.disarm()
        assert gripper.closed
        assert FakeBot.instances[-1].closed == 1
    finally:
        worker.close()


def test_gripper_preflight_failure_does_not_start_arm_motion(tmp_path):
    class InactiveGripper:
        def start(self):
            raise RuntimeError("gripper not activated")

        def close(self):
            pass

    worker, inbox, _ = make_worker(tmp_path, gripper_factory=InactiveGripper)
    try:
        send_leader(inbox, 0, [0.1] * 6)
        with pytest.raises(RuntimeError, match="not activated"):
            worker.arm()
        assert not FakeBot.instances
        assert inbox.latched is True
        assert worker.status()["armed"] is False
    finally:
        worker.close()


def test_arm_waits_for_rt_callbacks_and_fresh_gripper_feedback(tmp_path):
    from xcore_controller.gripper import GripperFeedbackPending

    class WarmingBot(FakeBot):
        def motion_active(self):
            return len(self.targets) >= 3

        def stats(self):
            return {"cb_calls": len(self.targets)}

    class WarmingGripper:
        def __init__(self):
            self.polls = 0
            self.submitted = []

        def start(self):
            pass

        def feedback(self):
            self.polls += 1
            if self.polls < 4:
                raise GripperFeedbackPending("gripper feedback is stale")
            return {
                "closure": 0.3,
                "position_raw": 77,
                "feedback_time_ns": time.monotonic_ns(),
            }

        def submit(self, ticks):
            self.submitted.append(ticks)
            return dict(self.feedback(), target_closure=0.4)

        def close(self):
            pass

    grip = WarmingGripper()
    worker, inbox, _ = make_worker(
        tmp_path,
        gripper_factory=lambda: grip,
        bot_factory=WarmingBot,
    )
    try:
        send_leader(inbox, 0, [0.1] * 6)
        status = worker.arm()
        assert status["state"] == "following" and status["armed"]
        assert grip.polls >= 4
        assert WarmingBot.instances[-1].stats()["cb_calls"] >= 3
        worker.disarm()
    finally:
        worker.close()


def test_arm_reports_async_rt_startup_failure_to_http_caller(tmp_path):
    class FailedStartup(FakeBot):
        def abort_reason(self):
            return "Attempted to start multiple motions!" if self.targets else None

        def motion_active(self):
            return False

    worker, inbox, _ = make_worker(tmp_path, bot_factory=FailedStartup)
    try:
        send_leader(inbox, 0, [0.1] * 6)
        with pytest.raises(RuntimeError, match="multiple motions"):
            worker.arm()
        assert worker.status()["armed"] is False
        assert "multiple motions" in worker.status()["abort_reason"]
        assert FailedStartup.instances[-1].closed == 1
        assert inbox.latched
    finally:
        worker.close()


def test_stale_stream_stops_following(tmp_path):
    worker, inbox, _ = make_worker(tmp_path, stale=0.1)
    send_leader(inbox, 0, [0.1] * 6)
    worker.arm()
    send_leader(inbox, 1, [0.11] * 6)
    wait_for(lambda: worker.status()["forwarded"] > 0)
    wait_for(lambda: worker.status()["state"] == "stopped", timeout=3)
    assert "leader stream failure" in worker.status()["abort_reason"]
    assert FakeBot.instances[-1].closed == 1
    worker.close()


def test_exit_returns_to_captured_start(tmp_path):
    worker, inbox, driver = make_worker(tmp_path, return_mode="start")
    driver.values = [0.3] * 6
    captured = worker.capture_start()["start_pose_rad"]
    assert captured == [0.3] * 6
    driver.values = [0.5] * 6
    result = worker.return_to("start")
    assert result["returned"] is True
    assert driver.moves[-1][0] == [0.3] * 6
    # The pre-return power/mode are restored after the NRT motion.
    assert driver.power_value.name == "off"
    assert driver.mode_value.name == "manual"
    worker.close()


def test_return_none_does_not_move(tmp_path):
    worker, _, driver = make_worker(tmp_path, return_mode="none")
    result = worker.return_to("none")
    assert result["returned"] is False
    assert driver.moves == []
    worker.close()


def test_return_fault_does_not_repower_controller_during_cleanup(tmp_path):
    worker, _, driver = make_worker(tmp_path, return_mode="zero")
    driver.power_value = Enum("on")

    def failed_move(*args, **kwargs):
        driver.power_value = Enum("off")
        raise RuntimeError("controller protection powered off")

    driver.movej = failed_move
    try:
        with pytest.raises(RuntimeError, match="controller protection powered off"):
            worker.return_to("zero")
        assert driver.power_value == driver.sdk.PowerState.off
    finally:
        worker.close()


def test_return_waits_for_rt_shutdown_to_reach_idle(tmp_path):
    class SlowIdleDriver(FakeDriver):
        def __init__(self):
            super().__init__()
            self.non_idle = 3

        def call(self, name, *args):
            if name == "operationState" and self.non_idle:
                self.non_idle -= 1
                return Enum("moving")
            return super().call(name, *args)

    worker, _, _ = make_worker(tmp_path, return_mode="zero")
    slow = SlowIdleDriver()
    slow.values = [0.2] * 6
    worker._driver = slow
    result = worker.return_to("zero")
    assert result["returned"] is True
    assert slow.moves[-1][0] == [0.0] * 6
    worker.close()


def test_shutdown_returns_then_powers_off(tmp_path):
    worker, inbox, driver = make_worker(tmp_path, return_mode="zero")
    driver.values = [0.2] * 6
    result = worker.shutdown("zero")
    assert result["returned"] is True
    assert result["powered_off"] is True
    assert driver.moves[-1][0] == [0.0] * 6
    assert driver.power_value.name == "off"
    worker.close()
