from xcore_controller.cli import COMMAND_TIMEOUTS


def test_motion_commands_are_not_bounded_by_the_status_timeout():
    # prepare/return run NRT motion and legitimately take minutes; a 2 s client
    # timeout used to abort the launcher while the robot kept moving.
    assert COMMAND_TIMEOUTS["prepare"] >= 600
    assert COMMAND_TIMEOUTS["exit"] >= 600
    assert COMMAND_TIMEOUTS["return"] >= 600
    assert COMMAND_TIMEOUTS["episode/save"] >= 60
    assert COMMAND_TIMEOUTS["arm"] >= 30
