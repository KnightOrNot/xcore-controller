"""Map raw GELLO ticks to CR7 joint targets on the remote controller.

The leader samples are single-turn Dynamixel positions. Unwrapping, calibration
offset/sign and the 2*pi branch are applied here, once, on the remote side; the
local GELLO service only publishes raw ticks.
"""

from __future__ import annotations

import math

import numpy as np

TICKS_PER_PI = 2048.0
HOLD_TOLERANCE_RAD = math.radians(0.5)


class MappingError(RuntimeError):
    """Raised when a leader sample cannot be mapped safely."""


def wrap_pi(value):
    return (np.asarray(value, dtype=float) + math.pi) % (2 * math.pi) - math.pi


def ticks_to_rad(ticks):
    return np.asarray(ticks, dtype=float) / TICKS_PER_PI * math.pi


class LeaderMapper:
    def __init__(self, offsets, signs, *, jump_guard_rad: float = 1.0):
        self.offsets = np.asarray(offsets, dtype=float)
        self.signs = np.asarray(signs, dtype=float)
        if self.offsets.shape != (6,) or not np.all(np.isfinite(self.offsets)):
            raise ValueError("mapping requires six finite offsets")
        if self.signs.shape != (6,) or not np.all(np.isin(self.signs, (-1, 1))):
            raise ValueError("mapping signs must each be -1 or 1")
        if not math.isfinite(jump_guard_rad) or jump_guard_rad <= 0:
            raise ValueError("jump guard must be positive")
        self.jump_guard = float(jump_guard_rad)
        self._previous = None
        self._continuous = None
        self._branch = np.zeros(6)

    def reset(self):
        self._previous = None
        self._continuous = None
        self._branch = np.zeros(6)

    def rad(self, ticks):
        """Single-turn ticks -> continuously unwrapped leader radians."""
        raw = ticks_to_rad(ticks[:6])
        if raw.shape != (6,) or not np.all(np.isfinite(raw)):
            raise MappingError("leader sample must contain six finite ticks")
        if self._continuous is None:
            self._previous = raw.copy()
            self._continuous = raw.copy()
            return raw.copy()
        delta = wrap_pi(raw - self._previous)
        if np.max(np.abs(delta)) > self.jump_guard:
            raise MappingError(
                f"leader sample jumped {np.max(np.abs(delta)):.3f} rad; "
                "rejected as a read glitch"
            )
        self._previous = raw.copy()
        self._continuous = self._continuous + delta
        return self._continuous.copy()

    def target(self, raw, reference):
        """Choose the 2*pi branch nearest to `reference` and return absolute targets."""
        mapped = (np.asarray(raw, dtype=float) - self.offsets) * self.signs
        self._branch = np.round((mapped - np.asarray(reference)) / (2 * math.pi))
        return mapped - self._branch * 2 * math.pi

    def follow(self, raw):
        """Apply the branch fixed at arming; no hidden re-branching mid-follow."""
        mapped = (np.asarray(raw, dtype=float) - self.offsets) * self.signs
        return mapped - self._branch * 2 * math.pi

    def feed_ticks(self, ticks):
        raw = self.rad(ticks)
        return self.follow(raw)

    def held(self, ticks_samples):
        """True when all samples are within the hold tolerance (dead band)."""
        values = np.asarray(
            [ticks_to_rad(sample[:6]) for sample in ticks_samples], dtype=float
        )
        if values.ndim != 2 or values.shape[1] != 6 or values.shape[0] < 2:
            return False
        return float(np.max(np.ptp(values, axis=0))) <= HOLD_TOLERANCE_RAD


def closure_from_tick(tick, open_deg: float, close_deg: float) -> float:
    """Map trigger ID7 angle to [0,1]; 0 open, 1 closed."""
    if open_deg == close_deg:
        raise ValueError("gripper open and close angles must differ")
    value = (math.degrees(ticks_to_rad([tick])[0]) - open_deg) / (close_deg - open_deg)
    return float(min(max(value, 0.0), 1.0))
