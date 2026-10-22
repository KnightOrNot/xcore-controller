import numpy as np
import pytest

from xcore_controller.kinematics import KinematicsError, VendorKinematics


class Model:
    def __init__(self, value):
        self.value = value

    def getCartPose(self, joints):
        return self.value


def transform():
    matrix = np.eye(4)
    matrix[:3, 3] = [0.4, 0.2, 0.3]
    return matrix.ravel().tolist()


def test_pose10_from_vendor_row_major_matrix():
    kinematics = VendorKinematics(Model(transform()))
    result = kinematics.state([0] * 6, 0.25)
    assert result.shape == (10,)
    assert np.allclose(result[:3], [0.4, 0.2, 0.3])
    assert np.allclose(result[3:6], [1, 0, 0])
    assert np.allclose(result[6:9], [0, 1, 0])
    assert result[9] == 0.25


def test_rejects_non_homogeneous_or_wrong_shape():
    bad = np.eye(4)
    bad[3, 0] = 1
    with pytest.raises(KinematicsError, match="homogeneous"):
        VendorKinematics(Model(bad.ravel().tolist())).transform([0] * 6)
    with pytest.raises(KinematicsError, match="finite 4x4"):
        VendorKinematics(Model([1, 2, 3])).transform([0] * 6)
    with pytest.raises(KinematicsError, match="six finite"):
        VendorKinematics(Model(transform())).transform([0] * 5)
