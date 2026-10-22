import math

import numpy as np
import pytest

from xcore_controller.mapping import (
    LeaderMapper,
    MappingError,
    closure_from_tick,
    ticks_to_rad,
)


def ticks(radians):
    return [round(value / math.pi * 2048) for value in radians]


def test_maps_offsets_signs_and_nearest_branch():
    mapper = LeaderMapper([0.2] * 6, [1, -1, 1, -1, 1, -1])
    raw = ticks_to_rad(ticks([0.5] * 6))
    reference = np.array([0.3, -0.3, 0.3, -0.3, 7.0, -7.0])
    target = mapper.target(raw, reference)
    mapped = (raw - 0.2) * np.array([1, -1, 1, -1, 1, -1])
    assert np.allclose(target[:4], mapped[:4])
    # Branches keep every axis within pi of the reference.
    assert np.all(np.abs(target - reference) <= math.pi + 1e-9)
    assert target[4] > 6 and target[5] < -6


def test_unwrap_tracks_crossing_and_rejects_glitch():
    mapper = LeaderMapper([0.0] * 6, [1] * 6, jump_guard_rad=0.5)
    first = mapper.rad(ticks([3.0] * 6))
    second = mapper.rad(ticks([-3.0] * 6))
    # Crossing +pi continues upward instead of wrapping back by 2*pi.
    assert np.all(second > first)
    assert np.allclose(second - first, 2 * math.pi - 6.0, atol=1e-3)
    with pytest.raises(MappingError, match="jumped"):
        mapper.rad(ticks([2.0] * 6))


def test_hold_detection_and_closure():
    mapper = LeaderMapper([0.0] * 6, [1] * 6)
    steady = [ticks([0.4] * 6) for _ in range(5)]
    assert mapper.held(steady)
    moved = steady + [ticks([0.45, 0.4, 0.4, 0.4, 0.4, 0.4])]
    assert not mapper.held(moved)
    open_tick = round(194.8 / 180 * 2048)
    close_tick = round(153.0 / 180 * 2048)
    assert closure_from_tick(open_tick, 194.8, 153.0) == pytest.approx(0, abs=1e-3)
    assert closure_from_tick(close_tick, 194.8, 153.0) == pytest.approx(1, abs=1e-3)
    assert closure_from_tick(0, 194.8, 153.0) == 1.0
