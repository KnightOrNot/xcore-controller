import pytest

from xcore_controller.launcher import main


def test_pose_and_joints_are_mutually_exclusive_before_ssh():
    with pytest.raises(SystemExit) as error:
        main(["pull", "--pose", "--joints", "dataset", "rev-0001"])
    assert error.value.code == 2


def test_pull_requires_dataset_and_revision():
    with pytest.raises(ValueError, match="DATASET_ID"):
        main(["pull"])
    with pytest.raises(ValueError, match="DATASET_ID"):
        main(["pull", "--joints", "dataset"])
