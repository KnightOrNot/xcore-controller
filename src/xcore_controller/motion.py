"""Remote CR7 motion worker: one SDK owner, explicit arm, stale stop.

All SDK calls happen on the worker thread. HTTP handlers enqueue an action and
wait for its result; they never touch the vendor extension directly. Following
is opt-in: constructing the worker connects and reads feedback only.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .mapping import LeaderMapper, MappingError, ticks_to_rad


@dataclass(frozen=True)
class MotionSettings:
    ip: str
    local_ip: str = ""
    sdk_dir: str = ""
    lock_path: str = ""
    calibration: str = ""
    max_speed_deg: float = 3.0
    accel_deg_s2: float = 40.0
    control_hz: float = 25.0
    stale_timeout_s: float = 1.0
    gate_deg: float = 17.1887
    prepare_speed: float = 1000.0
    prepare_samples: int = 30
    prepare_interval_s: float = 0.03
    prepare_max_step_deg: float = 180.0
    prepare_tolerance_deg: float = 0.2
    prepare_timeout_s: float = 600.0
    return_speed: float = 1000.0
    return_max_step_deg: float = 360.0
    return_tolerance_deg: float = 0.2
    return_timeout_s: float = 600.0
    return_mode: str = "none"
    arm_timeout_s: float = 20.0

    def validate(self) -> None:
        for name in (
            "max_speed_deg",
            "accel_deg_s2",
            "control_hz",
            "stale_timeout_s",
            "gate_deg",
            "arm_timeout_s",
            "prepare_speed",
            "prepare_interval_s",
            "prepare_max_step_deg",
            "prepare_tolerance_deg",
            "prepare_timeout_s",
            "return_speed",
            "return_max_step_deg",
            "return_tolerance_deg",
            "return_timeout_s",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive and finite")
        if self.max_speed_deg > 75:
            raise ValueError("max_speed_deg is limited to 75 deg/s")
        if not 1 <= self.arm_timeout_s <= 30:
            raise ValueError("arm_timeout_s must be in 1..30 seconds")
        if not 5 <= self.prepare_speed <= 4000:
            raise ValueError("prepare_speed must be in 5..4000 mm/s")
        if not 5 <= self.return_speed <= 4000:
            raise ValueError("return_speed must be in 5..4000 mm/s")
        if not isinstance(self.prepare_samples, int) or self.prepare_samples < 2:
            raise ValueError("prepare_samples must be at least 2")
        if self.return_mode not in ("start", "zero", "none"):
            raise ValueError("return_mode must be start, zero or none")


def _default_driver(settings: MotionSettings):
    from xcore_sdk_python.driver import RobotDriver

    return RobotDriver(
        settings.ip,
        local_ip=settings.local_ip,
        sdk_dir=settings.sdk_dir or None,
    )


def _default_bot(driver: Any, settings: MotionSettings, verbose: bool):
    from xcore_sdk_python.gello_follower import GelloCr7Robot
    from xcore_sdk_python.gello_server import CheckedRobot

    return GelloCr7Robot(
        CheckedRobot(driver.robot),
        driver.sdk,
        enable_motion=True,
        control_hz=settings.control_hz,
        max_speed=math.radians(settings.max_speed_deg),
        accel=math.radians(settings.accel_deg_s2),
        stale_timeout=settings.stale_timeout_s,
        arm_gate_rad=math.radians(settings.gate_deg),
        verbose=verbose,
    )


@dataclass
class _Command:
    action: str
    payload: dict[str, Any]
    event: threading.Event
    result: Any = None
    error: Exception | None = None


class MotionWorker:
    """Own the SDK session and forward mapped targets while explicitly armed."""

    def __init__(
        self,
        settings: MotionSettings,
        inbox: Any,
        lock: threading.RLock,
        *,
        driver_factory: Callable[[], Any] | None = None,
        bot_factory: Callable[[Any, MotionSettings, bool], Any] | None = None,
        gripper_factory: Callable[[], Any] | None = None,
        verbose: bool = True,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.inbox, self._inbox_lock = inbox, lock
        self.verbose = verbose
        self._driver_factory = driver_factory or (lambda: _default_driver(settings))
        self._bot_factory = bot_factory or _default_bot
        self._gripper_factory = gripper_factory
        self._gripper: Any = None
        self._gripper_feedback: dict[str, Any] | None = None
        self._commands: queue.Queue[_Command] = queue.Queue()
        self._stop = threading.Event()
        self._cancel_arm = threading.Event()
        self._lock = threading.RLock()
        self._driver: Any = None
        self._bot: Any = None
        self._mapper = LeaderMapper(*_load_calibration(settings.calibration))
        self._state = "starting"
        self._error: str | None = None
        self._abort: str | None = None
        self._cleanup_fault: str | None = None
        self._armed = False
        self._start_pose: list[float] | None = None
        self._last_feedback: list[float] | None = None
        self._last_target: list[float] | None = None
        self._last_sample_ns: int | None = None
        self._last_state_pose: list[float] | None = None
        self._last_target_pose: list[float] | None = None
        self._last_feedback_ns: int | None = None
        self._last_sample: dict[str, Any] | None = None
        self._soft_lo: Any = None
        self._soft_hi: Any = None
        self._kinematics: Any = None
        self._fk_error: str | None = None
        self._forwarded = 0
        self._thread = threading.Thread(target=self._run, name="motion", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- lifecycle
    def _run(self) -> None:
        driver = None
        try:
            import contextlib

            from .roles import lock_device

            lock = (
                lock_device(self.settings.lock_path)
                if self.settings.lock_path
                else contextlib.nullcontext()
            )
            with lock:
                driver = self._driver_factory()
                driver.__enter__()
                with self._lock:
                    self._driver = driver
                    self._state = "idle"
                self._init_kinematics(driver)
                if self.verbose:
                    print("remote motion worker connected (dry, not armed)")
                while not self._stop.is_set():
                    try:
                        command = self._commands.get(timeout=0.02)
                    except queue.Empty:
                        command = None
                    if command is not None:
                        self._execute(command)
                    if self._armed:
                        self._forward()
        except Exception as exc:  # noqa: BLE001 - report every startup failure
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
                self._state = "error"
        finally:
            self._close_bot()
            if driver is not None:
                try:
                    driver.close()
                except Exception:
                    pass
            with self._lock:
                self._driver = None
                if self._state not in ("error",):
                    self._state = "closed"

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise RuntimeError("motion worker did not exit")

    # ------------------------------------------------------------------ commands
    def _call(
        self, action: str, payload: dict[str, Any] | None = None, timeout: float = 60
    ) -> Any:
        if not self._thread.is_alive():
            raise RuntimeError(self._error or "motion worker is not running")
        command = _Command(action, payload or {}, threading.Event())
        self._commands.put(command)
        if not command.event.wait(timeout):
            raise TimeoutError(f"motion command {action} timed out")
        if command.error is not None:
            raise command.error
        return command.result

    def arm(self) -> dict[str, Any]:
        self._cancel_arm.clear()
        return self._call("arm", timeout=self.settings.arm_timeout_s + 15)

    def disarm(self) -> dict[str, Any]:
        self._cancel_arm.set()
        return self._call("disarm", timeout=30)

    def prepare(self) -> dict[str, Any]:
        return self._call("prepare", timeout=self.settings.prepare_timeout_s + 30)

    def return_to(self, mode: str | None = None) -> dict[str, Any]:
        return self._call(
            "return",
            {"mode": mode or self.settings.return_mode},
            timeout=self.settings.return_timeout_s + 30,
        )

    def capture_start(self) -> dict[str, Any]:
        return self._call("capture-start", timeout=10)

    def pose(self) -> dict[str, Any]:
        return self._call("pose", timeout=10)

    # ------------------------------------------------------------------- state
    def sample(self) -> dict[str, Any] | None:
        """Latest measured/commanded sample for the recorder; never blocks RT."""
        with self._lock:
            return None if self._last_sample is None else dict(self._last_sample)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "armed": self._armed,
                "return_mode": self.settings.return_mode,
                "error": self._error,
                "abort_reason": self._abort,
                "forwarded": self._forwarded,
                "last_feedback_rad": self._last_feedback,
                "last_target_rad": self._last_target,
                "last_sample_ns": self._last_sample_ns,
                "last_state_pose10": self._last_state_pose,
                "last_target_pose10": self._last_target_pose,
                "kinematics": getattr(self._kinematics, "name", None),
                "fk_error": self._fk_error,
                "start_pose_rad": self._start_pose,
                "gripper_enabled": self._gripper_factory is not None,
                "gripper": self._gripper_feedback,
                "cleanup_fault": self._cleanup_fault,
            }

    def _execute(self, command: _Command) -> None:
        try:
            handler = getattr(self, "_do_" + command.action.replace("-", "_"))
            command.result = handler(command.payload)
        except Exception as exc:  # noqa: BLE001 - returned to the HTTP caller
            command.error = exc
        finally:
            command.event.set()

    # ----------------------------------------------------------- command bodies
    def _do_arm(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._armed:
                return self.status()
            if self._state not in ("idle", "stopped") or self._driver is None:
                raise RuntimeError(f"cannot arm while motion is {self._state}")
            driver = self._driver
            if self._cleanup_fault:
                raise RuntimeError(self._cleanup_fault)
        with self._inbox_lock:
            packet = self.inbox.check()
        feedback = np.asarray(driver.joints()["rad"], dtype=float)
        raw = self._mapper.rad(packet["ticks"])
        target = self._mapper.target(raw, feedback)
        error = float(np.max(np.abs(target - feedback)))
        if error > math.radians(self.settings.gate_deg):
            raise RuntimeError(
                f"refusing to arm: leader/robot difference {math.degrees(error):.1f}° "
                f"exceeds gate {self.settings.gate_deg}°"
            )
        limits = driver.limits()
        from xcore_sdk_python.follow_limits import intersect_soft_limits

        soft_lo, soft_hi = intersect_soft_limits(
            limits["rad"], enabled=limits["enabled"]
        )
        with self._lock:
            self._soft_lo, self._soft_hi = soft_lo, soft_hi
        if self.settings.return_mode == "start":
            self._start_pose = feedback.tolist()
        self._init_kinematics(driver)
        gripper = None
        try:
            if self._gripper_factory is not None:
                gripper = self._gripper_factory()
                gripper.start()  # Read-only capability/activation preflight.
            with self._inbox_lock:
                self.inbox.check()  # Slow preflight must not arm stale input.
            bot = self._bot_factory(driver, self.settings, self.verbose)
            with self._lock:
                self._bot = bot
                self._gripper = gripper
                self._state = "arming"
                self._last_sample = None
                self._error = self._abort = None
                self._forwarded = 0
            self._wait_arm_ready(bot, gripper, feedback)
            with self._inbox_lock:
                packet = self.inbox.check()
                target = self._mapper.feed_ticks(packet["ticks"])
                actual = np.asarray(bot.get_joint_state(), dtype=float)
                if np.max(np.abs(target - actual)) > math.radians(
                    self.settings.gate_deg
                ):
                    raise RuntimeError(
                        "GELLO moved outside the alignment gate during arm"
                    )
                self.inbox.arm()
        except BaseException as exc:
            # The HTTP caller must see startup failures, rather than a false
            # armed=true followed by a silent asynchronous stop.
            attached = gripper is not None and self._gripper is gripper
            self._close_bot()
            with self._inbox_lock:
                self.inbox.latched = True
            with self._lock:
                self._armed = False
                self._state = "error" if self._cleanup_fault else "stopped"
                self._abort = f"arm failed: {type(exc).__name__}: {exc}"
            if gripper is not None and not attached:
                try:
                    gripper.close()
                except Exception as cleanup_exc:
                    self._cleanup_fault = f"gripper cleanup failed: {cleanup_exc}"
            raise
        with self._lock:
            self._armed = True
            self._error = None
            self._abort = None
            self._state = "following"
            self._last_feedback = feedback.tolist()
        if self.verbose:
            print(
                f"remote motion armed; gate error {math.degrees(error):.2f}°; "
                f"branch {self._mapper._branch.astype(int).tolist()}"
            )
        return self.status()

    def _wait_arm_ready(self, bot: Any, gripper: Any, feedback: Any) -> None:
        from .gripper import GripperFeedbackPending

        deadline = time.monotonic() + self.settings.arm_timeout_s
        while True:
            if self._stop.is_set() or self._cancel_arm.is_set():
                raise RuntimeError("arm cancelled")
            with self._inbox_lock:
                self.inbox.check()
            reason = bot.abort_reason()
            if reason:
                raise RuntimeError(reason)
            # Hold at measured startup pose while RT starts. Do not dispatch
            # leader/gripper targets until both independent components are ready.
            bot.command_joint_state(feedback)
            rt_ready = bot.motion_active() and bot.stats()["cb_calls"] >= 3
            grip_ready = gripper is None
            if gripper is not None:
                try:
                    self._gripper_feedback = gripper.feedback()
                    grip_ready = True
                except GripperFeedbackPending:
                    pass  # Bounded warmup only; normal follow still rejects stale.
            if rt_ready and grip_ready:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"arm startup timed out: rt_ready={rt_ready}, "
                    f"gripper_ready={grip_ready}"
                )
            time.sleep(min(0.04, 1 / self.settings.control_hz))

    def _do_disarm(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._close_bot()
        with self._inbox_lock:
            self.inbox.latched = True
        with self._lock:
            self._armed = False
            if self._state == "following":
                self._state = "idle"
        self._require_clean_shutdown()
        return self.status()

    def _do_capture_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            driver = self._require_driver()
        feedback = [float(v) for v in driver.joints()["rad"]]
        with self._lock:
            self._start_pose = feedback
        return {"start_pose_rad": feedback}

    def _do_pose(self, payload: dict[str, Any]) -> dict[str, Any]:
        driver = self._require_driver()
        feedback = [float(v) for v in driver.joints()["rad"]]
        with self._lock:
            kinematics = self._kinematics
            fk_error = self._fk_error
        result: dict[str, Any] = {
            "joints_rad": feedback,
            "kinematics": getattr(kinematics, "name", None),
            "tcp": "flange (identity toolset; gripper TCP not verified)",
            "fk_error": fk_error,
            "pose10": None,
            "controller_posture": None,
            "translation_difference_m": None,
        }
        if kinematics is not None:
            result["pose10"] = kinematics.state(feedback, 0.0).tolist()
            try:
                sdk = driver.sdk
                posture = driver.call("posture", sdk.CoordinateType.flangeInBase)
                result["controller_posture"] = list(posture)
                controller = sdk.utility.postureToTransArray(list(posture))
                matrix = kinematics.transform(feedback)
                result["translation_difference_m"] = [
                    float(matrix[i, 3] - controller[i * 4 + 3]) for i in range(3)
                ]
            except Exception as exc:  # noqa: BLE001 - audit only, never motion
                result["controller_posture_error"] = f"{type(exc).__name__}: {exc}"
        return result

    def _do_prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_clean_shutdown()
        driver = self._require_driver()
        with self._lock:
            if self._armed:
                raise RuntimeError("disarm before preparing")
        samples = self._sample_ticks()
        if not self._mapper.held(samples):
            raise RuntimeError("hold GELLO still during preparation")
        mean_raw = np.mean([ticks_to_rad(s[:6]) for s in samples], axis=0)
        feedback = np.asarray(driver.joints()["rad"], dtype=float)
        self._mapper.reset()
        raw = self._mapper.rad(samples[-1])
        target = self._mapper.target(raw, feedback)
        self._validate_leg(driver, feedback, target, self.settings.prepare_max_step_deg)
        self._wait_idle(driver)
        power = driver.call("powerState")
        mode = driver.call("operateMode")
        attempted = False
        failure = None
        try:
            if float(np.max(np.abs(target - feedback))) <= math.radians(
                self.settings.prepare_tolerance_deg
            ):
                return {"reached": True, "skipped": True, "target_rad": target.tolist()}
            attempted = True
            driver.call(
                "setMotionControlMode", driver.sdk.MotionControlMode.NrtCommandMode
            )
            driver.mode("automatic")
            driver.power(True)
            result = driver.movej(
                target.tolist(),
                speed=self.settings.prepare_speed,
                max_step_deg=self.settings.prepare_max_step_deg,
                tolerance_deg=self.settings.prepare_tolerance_deg,
                motion_timeout=self.settings.prepare_timeout_s,
                motion_mode_prepared=True,
            )
            return dict(
                result,
                target_rad=target.tolist(),
                mean_leader_rad=mean_raw.tolist(),
            )
        except BaseException as exc:
            failure = exc
            raise
        finally:
            if attempted:
                try:
                    _restore(driver, power, mode, allow_power_on=failure is None)
                except Exception:
                    if failure is None:
                        raise

    def _do_return(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = payload.get("mode", "none")
        if mode not in ("start", "zero", "none"):
            raise ValueError("return mode must be start, zero or none")
        self._close_bot()
        self._require_clean_shutdown()
        with self._lock:
            self._armed = False
            self._state = "idle" if self._driver is not None else self._state
        if mode == "none":
            return {"returned": False, "mode": mode}
        driver = self._require_driver()
        self._wait_idle(driver)
        if mode == "zero":
            target = [0.0] * 6
        else:
            with self._lock:
                target = None if self._start_pose is None else list(self._start_pose)
            if target is None:
                raise RuntimeError("start return requested without a captured pose")
        feedback = np.asarray(driver.joints()["rad"], dtype=float)
        self._validate_leg(driver, feedback, target, self.settings.return_max_step_deg)
        power = driver.call("powerState")
        prior_mode = driver.call("operateMode")
        attempted = False
        failure = None
        try:
            if float(np.max(np.abs(np.asarray(target) - feedback))) <= math.radians(
                self.settings.return_tolerance_deg
            ):
                return {"returned": True, "skipped": True, "target_rad": target}
            attempted = True
            driver.call(
                "setMotionControlMode", driver.sdk.MotionControlMode.NrtCommandMode
            )
            driver.mode("automatic")
            driver.power(True)
            result = driver.movej(
                target,
                speed=self.settings.return_speed,
                max_step_deg=self.settings.return_max_step_deg,
                tolerance_deg=self.settings.return_tolerance_deg,
                motion_timeout=self.settings.return_timeout_s,
                motion_mode_prepared=True,
            )
            return dict(result, returned=True, mode=mode, target_rad=target)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            if attempted:
                try:
                    _restore(driver, power, prior_mode, allow_power_on=failure is None)
                except Exception:
                    if failure is None:
                        raise

    # ------------------------------------------------------------------ helpers
    def _init_kinematics(self, driver: Any) -> None:
        try:
            from .kinematics import VendorKinematics

            with self._lock:
                self._kinematics = VendorKinematics(driver.robot.model())
                self._fk_error = None
        except Exception as exc:  # noqa: BLE001 - reported as an invalid data stream
            with self._lock:
                self._kinematics = None
                self._fk_error = f"{type(exc).__name__}: {exc}"
            if self.verbose:
                print(f"FK unavailable; EE10 recording will be invalid: {exc}")

    def _wait_idle(self, driver: Any, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while driver.call("operationState") != driver.sdk.OperationState.idle:
            if time.monotonic() >= deadline:
                state = driver.call("operationState")
                raise RuntimeError(
                    f"robot did not return to idle before motion: {state.name}; "
                    "check the teach pendant"
                )
            time.sleep(0.05)

    def _require_driver(self) -> Any:
        with self._lock:
            if self._driver is None:
                raise RuntimeError(self._error or "SDK is not connected")
            return self._driver

    def _require_clean_shutdown(self) -> None:
        if self._cleanup_fault:
            raise RuntimeError(
                f"RT/gripper cleanup incomplete: {self._cleanup_fault}; "
                "restart the controller service after checking the robot; "
                "no new motion was dispatched"
            )

    def _sample_ticks(self) -> list[list[int]]:
        samples = []
        for _ in range(self.settings.prepare_samples):
            with self._inbox_lock:
                packet = self.inbox.check()
            samples.append(list(packet["ticks"]))
            time.sleep(self.settings.prepare_interval_s)
        return samples

    def _validate_leg(self, driver: Any, current: Any, target: Any, max_step_deg):
        from xcore_sdk_python.follow_limits import (
            intersect_soft_limits,
            limit_violation,
        )

        limits = driver.limits()
        lo, hi = intersect_soft_limits(limits["rad"], enabled=limits["enabled"])
        for label, posture in (("current", current), ("target", target)):
            violation = limit_violation(posture, lo, hi)
            if violation is not None:
                raise RuntimeError(f"{label} posture exceeds soft limits: {violation}")
        step = float(np.max(np.abs(np.asarray(target) - np.asarray(current))))
        if step > math.radians(max_step_deg):
            raise RuntimeError(
                f"motion step {math.degrees(step):.1f}° exceeds {max_step_deg}°"
            )

    def _forward(self) -> None:
        with self._lock:
            bot = self._bot
            if bot is None:
                self._armed = False
                return
        try:
            with self._inbox_lock:
                packet = self.inbox.target()
            requested = self._mapper.feed_ticks(packet["ticks"])
            with self._lock:
                lo, hi = self._soft_lo, self._soft_hi
            if lo is None or hi is None:
                raise RuntimeError("soft limits were not resolved at arming")
            target = np.clip(requested, lo, hi)
            bot.command_joint_state(target)
            reason = bot.abort_reason()
            feedback = bot.get_joint_state()
            gripper_feedback = (
                self._gripper.submit(packet["ticks"])
                if self._gripper is not None
                else None
            )
            feedback_ns = time.monotonic_ns()
        except (TimeoutError, MappingError) as exc:
            with self._inbox_lock:
                age = (
                    (time.monotonic_ns() - self.inbox.received_ns) / 1e9
                    if self.inbox.received_ns
                    else -1
                )
            self._stop_following(
                f"leader stream failure after {age:.2f}s without a sample "
                f"(timeout {self.settings.stale_timeout_s:.1f}s): {exc}"
            )
            return
        except Exception as exc:  # noqa: BLE001 - never let the loop die silently
            self._stop_following(f"target dispatch failed: {type(exc).__name__}: {exc}")
            return
        kinematics = self._kinematics
        state_pose = target_pose = None
        closure = gripper_feedback["closure"] if gripper_feedback else 0.0
        target_closure = gripper_feedback["target_closure"] if gripper_feedback else 0.0
        if kinematics is not None:
            try:
                state_pose = kinematics.state(feedback, closure).tolist()
                target_pose = kinematics.state(target, target_closure).tolist()
                with self._lock:
                    self._fk_error = None
            except Exception as exc:  # noqa: BLE001 - keep motion, flag samples
                with self._lock:
                    self._fk_error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._last_target = np.asarray(target).tolist()
            self._last_feedback = np.asarray(feedback).tolist()
            self._last_sample_ns = packet.get("source_monotonic_ns")
            self._last_state_pose = state_pose
            self._last_target_pose = target_pose
            self._last_feedback_ns = feedback_ns
            self._gripper_feedback = gripper_feedback
            self._last_sample = {
                "timestamp_ns": feedback_ns,
                "joints_rad": np.asarray(feedback).tolist(),
                "requested_target_rad": np.asarray(requested).tolist(),
                "target_rad": np.asarray(target).tolist(),
                "state_pose10": state_pose,
                "target_pose10": target_pose,
                "closure": closure,
                "target_closure": target_closure,
                "gripper_enabled": self._gripper_factory is not None,
                "gripper_feedback_time_ns": (
                    gripper_feedback["feedback_time_ns"] if gripper_feedback else None
                ),
                "gripper_position_raw": (
                    gripper_feedback["position_raw"] if gripper_feedback else None
                ),
                "leader_sequence": packet.get("sequence"),
                "leader_source_monotonic_ns": packet.get("source_monotonic_ns"),
                "leader_instance": packet.get("instance"),
                "fk_error": self._fk_error,
            }
            self._forwarded += 1
        if reason:
            self._stop_following(f"follow aborted: {reason}")

    def _stop_following(self, reason: str) -> None:
        self._close_bot()
        with self._inbox_lock:
            self.inbox.latched = True
        with self._lock:
            self._armed = False
            self._abort = reason
            self._state = "error" if self._cleanup_fault else "stopped"
        if self.verbose:
            print(f"remote motion stopped: {reason}")

    def _close_bot(self) -> None:
        with self._lock:
            bot, self._bot = self._bot, None
            gripper, self._gripper = self._gripper, None
            self._armed = False
        if bot is not None:
            try:
                bot.close()
            except Exception as exc:  # noqa: BLE001 - shutdown must stay best-effort
                with self._lock:
                    self._error = f"bot shutdown failed: {exc}"
                    self._cleanup_fault = self._error
        if gripper is not None:
            try:
                gripper.close()
            except Exception as exc:
                with self._lock:
                    self._error = f"gripper shutdown failed: {exc}"
                    self._cleanup_fault = self._error


def _restore(
    driver: Any, power: Any, mode: Any, *, allow_power_on: bool = True
) -> None:
    driver.stop()
    deadline = time.monotonic() + 5
    while driver.call("operationState") != driver.sdk.OperationState.idle:
        if time.monotonic() >= deadline:
            raise RuntimeError("robot did not stop; verify the teach pendant")
        time.sleep(0.05)
    # A failed motion may have tripped controller protection. Restoring a prior
    # "on" value must not silently re-enable it during exception cleanup.
    if power != driver.sdk.PowerState.on or allow_power_on:
        driver.power(power == driver.sdk.PowerState.on)
    driver.mode(mode.name)


def _load_calibration(path: str):
    if not path:
        raise ValueError("remote motion requires a calibration file")
    from xcore_sdk_python.calibration import load_calibration

    return load_calibration(path)
