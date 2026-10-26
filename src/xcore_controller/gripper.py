"""Remote trigger mapping backed by the existing independent TCP follower.

Only start() performs a synchronous read-only check. submit() uses an in-memory
latest-target mailbox: the SDK owner never waits for gripper network I/O.
"""

from __future__ import annotations

import math
import time
from typing import Any

from .mapping import closure_from_tick


class GripperFeedbackPending(RuntimeError):
    """No fresh feedback yet; tolerated only inside bounded arm startup."""


class RemoteGripper:
    def __init__(
        self,
        config: Any,
        *,
        port: int,
        feedback_max_age_s: float,
        client: Any = None,
        follower_factory: Any = None,
    ) -> None:
        from xcore_sdk_python.gripper_follow import GripperFollowClient, GripperFollower

        if not math.isfinite(feedback_max_age_s) or feedback_max_age_s <= 0:
            raise ValueError("gripper feedback maximum age must be positive")
        self.config = config
        self._max_age = feedback_max_age_s
        self._client = client or GripperFollowClient(
            "127.0.0.1", port, config.timeout_s
        )
        self._factory = follower_factory or GripperFollower
        self._follower = None

    def start(self) -> None:
        initial = dict(self._client.check(), feedback_time_ns=time.monotonic_ns())
        self._follower = self._factory(
            self._client,
            hz=self.config.hz,
            speed=self.config.speed,
            force=self.config.force,
            open_pos=self.config.open_pos,
            closed_pos=self.config.closed_pos,
            stale_timeout=self.config.stale_timeout_s,
            initial_feedback=initial,
            poll_when_idle=True,
        )

    def feedback(self) -> dict[str, Any]:
        if self._follower is None:
            raise RuntimeError("gripper is not armed")
        # Check feedback before submitting: invalid feedback must not create a
        # new target. A latched TCP error is also checked by the follower.
        self._follower.check()
        feedback = self._follower.feedback()
        raw, stamp = feedback.get("position_raw"), feedback.get("feedback_time_ns")
        now = time.monotonic_ns()
        if type(raw) is not int or not 0 <= raw <= 255:
            raise RuntimeError("invalid measured gripper position")
        if type(stamp) is not int or not 0 < stamp <= now:
            raise RuntimeError("missing gripper feedback timestamp")
        if (now - stamp) / 1e9 > self._max_age:
            raise GripperFeedbackPending("gripper feedback is stale")
        closure = (raw - self.config.open_pos) / (
            self.config.closed_pos - self.config.open_pos
        )
        return {
            "closure": min(max(float(closure), 0.0), 1.0),
            "position_raw": raw,
            "feedback_time_ns": stamp,
        }

    def submit(self, ticks: list[int]) -> dict[str, Any]:
        feedback = self.feedback()
        target = closure_from_tick(
            ticks[6], self.config.open_deg, self.config.close_deg
        )
        self._follower.submit(target)
        return dict(feedback, target_closure=target)

    def close(self) -> None:
        follower, self._follower = self._follower, None
        if follower is not None:
            follower.close()
            follower.check()
