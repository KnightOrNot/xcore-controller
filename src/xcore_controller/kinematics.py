"""Wrapper for the vendor forward-kinematics model used by EE10 recording.

The same model and toolset produce both actual-state and target poses, so actions
are not polluted by mixing controller-reported and model-computed poses. The
toolset is the identity (flange); it is *not* a verified gripper TCP.
"""

from __future__ import annotations

import numpy as np
from xcore_adapters.pose import pose10


class KinematicsError(RuntimeError):
    pass


class VendorKinematics:
    def __init__(self, model, *, name: str = "vendor_flange_model"):
        if not hasattr(model, "getCartPose"):
            raise KinematicsError("vendor model lacks getCartPose")
        self.model = model
        self.name = name

    def transform(self, joints) -> np.ndarray:
        values = np.asarray(joints, dtype=float).ravel()
        if values.shape != (6,) or not np.all(np.isfinite(values)):
            raise KinematicsError("FK requires six finite joint values")
        try:
            raw = self.model.getCartPose(values.tolist())
        except Exception as exc:  # noqa: BLE001 - vendor call boundary
            raise KinematicsError(
                f"vendor FK failed: {type(exc).__name__}: {exc}"
            ) from exc
        matrix = np.asarray(raw, dtype=float).ravel()
        if matrix.shape != (16,) or not np.all(np.isfinite(matrix)):
            raise KinematicsError("vendor FK must return a finite 4x4 matrix")
        transform = matrix.reshape(4, 4)
        if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-6):
            raise KinematicsError("vendor FK returned an invalid homogeneous matrix")
        return transform

    def state(self, joints, closure: float = 0.0) -> np.ndarray:
        return pose10(self.transform(joints), closure)
