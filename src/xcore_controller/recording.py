"""Remote recording session: robot samples plus both lossless camera streams.

The recorder runs on its own thread. The motion worker only publishes its latest
sample; HTTP, PNG indexes and disk writes never run in the RT callback or the
motion thread. Episode publication is delegated to xcore-dataset's validated
raw writer, which requires every referenced image and writes COMMITTED.json.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class RecordingError(RuntimeError):
    """Raised when an episode cannot be recorded or published safely."""


@dataclass(frozen=True)
class RecordingSettings:
    raw_root: str
    task: str = "CR7 GELLO teleoperation"
    fps: float = 15.0
    camera_urls: tuple[str, str] = (
        "http://127.0.0.1:8086",
        "http://127.0.0.1:8087",
    )
    max_frame_age_s: float = 0.5

    def validate(self) -> None:
        if not self.raw_root.strip():
            raise ValueError("raw_root must not be empty")
        if not self.task.strip():
            raise ValueError("recording task must not be empty")
        if not math.isfinite(self.fps) or not 1 <= self.fps <= 60:
            raise ValueError("recording fps must be in 1..60")
        if not math.isfinite(self.max_frame_age_s) or self.max_frame_age_s <= 0:
            raise ValueError("camera max frame age must be positive")
        if len(self.camera_urls) != 2:
            raise ValueError("exactly two camera URLs are required")
        for url in self.camera_urls:
            if not url.startswith("http://127.0.0.1:"):
                raise ValueError("camera URLs must use remote loopback HTTP")


class CameraClient:
    def __init__(self, url: str, timeout: float = 5.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path: str, data: dict | None = None) -> Any:
        request = urllib.request.Request(self.url + path)
        if data is not None:
            request.data = json.dumps(data).encode()
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RecordingError(
                f"camera {self.url}{path}: {exc.read().decode(errors='replace')}"
            ) from exc
        except OSError as exc:
            raise RecordingError(f"camera {self.url}{path}: {exc}") from exc

    def status(self) -> dict:
        return self.request("/api/status")

    def start_capture(self) -> dict:
        return self.request("/api/start", {})

    def ensure_streaming(self, timeout: float = 20.0) -> dict:
        state = self.status()
        if state["state"] == "streaming":
            return state
        if state["state"] == "error":
            raise RecordingError(state.get("error") or "camera is in error state")
        self.start_capture()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.status()
            if state["state"] == "streaming":
                return state
            if state["state"] == "error":
                raise RecordingError(state.get("error") or "camera failed")
            time.sleep(0.1)
        raise RecordingError("camera did not start streaming in time")

    def start_recording(self, directory: Path, session: str, episode: str) -> dict:
        return self.request(
            "/api/record/start",
            {
                "directory": str(directory),
                "session": session,
                "episode": episode,
            },
        )

    def stop_recording(
        self, *, complete: bool = True, reason: str | None = None
    ) -> dict:
        return self.request(
            "/api/record/stop", {"complete": complete, "reason": reason}
        )

    def frames(self, after: int = -1, limit: int = 200) -> list[dict]:
        result = self.request(f"/api/record/frames?after={after}&limit={limit}")
        return result["frames"]


@dataclass
class _Episode:
    index: int
    directory: Path
    writer: Any
    cameras: dict[str, CameraClient]
    manifest: dict[str, Any]


class SessionRecorder:
    def __init__(
        self,
        settings: RecordingSettings,
        motion: Any,
        *,
        camera_factory=CameraClient,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.motion = motion
        self._camera_factory = camera_factory
        self._lock = threading.RLock()
        # Serialize lifecycle operations, but keep status and the recorder's
        # short state updates independent of camera I/O, hashing and joins.
        self._operation_lock = threading.RLock()
        self._session_id: str | None = None
        self._session_dir: Path | None = None
        self._task = settings.task
        self._episode_index = 0
        self._episode: _Episode | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"
        self._error: str | None = None
        self._rows = 0
        self._index: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ session
    def start_session(self, task: str | None = None) -> dict[str, Any]:
        with self._operation_lock:
            if self._session_id is not None:
                return self.status()
            task = (task or self.settings.task).strip()
            if not task:
                raise RecordingError("task must not be empty")
            root = Path(self.settings.raw_root).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            base = "session_" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            directory, suffix = root / base, 1
            while directory.exists():
                directory = root / f"{base}_{suffix:02d}"
                suffix += 1
            directory.mkdir()
            self._session_id, self._session_dir, self._task = base, directory, task
            self._episode_index, self._error, self._state = 0, None, "ready"
            _write_json(
                directory / "session.json",
                {
                    "format": "xcore_session_v1",
                    "session": base,
                    "created": datetime.now().astimezone().isoformat(),
                    "task": task,
                    "raw_fps": self.settings.fps,
                    "camera_urls": list(self.settings.camera_urls),
                    "clock": "remote_host_monotonic",
                    "robot_ip": self.motion.settings.ip,
                    "calibration": self.motion.settings.calibration,
                    "tcp": "flange (identity toolset; gripper TCP not verified)",
                    "action_source": "accepted_absolute_target_after_soft_limits",
                    "gripper": self._gripper_description(),
                    "wrench": "two sensors reserved; validity false",
                    "camera_max_frame_age_s": self.settings.max_frame_age_s,
                },
            )
            return self.status()

    # ------------------------------------------------------------------ episode
    def start_episode(self) -> dict[str, Any]:
        from xcore_dataset.raw import FORMAT, EpisodeWriter

        with self._operation_lock:
            if self._session_id is None or self._session_dir is None:
                raise RecordingError("start a session before an episode")
            if self._episode is not None:
                raise RecordingError("an episode is already active")
            status = self.motion.status()
            if not status.get("armed"):
                raise RecordingError(
                    "episode recording requires an armed follow session"
                )
            if status.get("fk_error"):
                raise RecordingError(f"FK is unavailable: {status['fk_error']}")
            cameras = {
                f"cam{i + 1}": self._camera_factory(url)
                for i, url in enumerate(self.settings.camera_urls)
            }
            metadata = {}
            for name, camera in cameras.items():
                state = camera.ensure_streaming()
                meta = state["metadata"]
                metadata[name] = {
                    "serial": meta["device"]["serial_number"],
                    "depth_scale_m_per_unit": meta["depth_scale_m_per_unit"],
                    "color_intrinsics": meta["color_intrinsics"],
                    "depth_intrinsics": meta["depth_intrinsics"],
                    "depth_to_color": meta["depth_to_color"],
                    "depth_alignment": meta.get("depth_alignment", "native_depth"),
                    "profile": meta["configuration"],
                    "image_clock": "remote_host_monotonic receive time",
                }
            index = self._episode_index
            directory = self._session_dir / "episodes" / f"episode_{index:06d}"
            manifest = {
                "format": FORMAT,
                "simulated": False,
                "task": self._task,
                "position_unit": "m",
                "rotation": "columns_0_1",
                "base_frame": "cr7_base",
                "tcp": "flange (identity toolset; gripper TCP not verified)",
                "action_source": "accepted_absolute_target_after_soft_limits",
                "cameras": metadata,
                "clock_domain": "remote_host_monotonic",
                "clock_note": "camera receive times are from the same remote host; "
                "this is software alignment, not hardware synchronization",
                "robot_model": "vendor getCartPose (same model for state/action)",
                "gripper": self._gripper_description(),
                "wrench": "two sensors reserved; validity false",
            }
            writer = EpisodeWriter(directory, manifest)
            started = []
            try:
                for name, camera in cameras.items():
                    camera.start_recording(
                        directory / name,
                        self._session_id,
                        f"episode_{index:06d}",
                    )
                    started.append(camera)
            except BaseException:
                for camera in started:
                    try:
                        camera.stop_recording(complete=False, reason="start failed")
                    except Exception:
                        pass
                writer.close()
                raise
            self._episode = _Episode(index, directory, writer, cameras, manifest)
            self._rows, self._error = 0, None
            self._index = {name: {"last": -1, "frames": []} for name in cameras}
            self._stop.clear()
            self._state = "recording"
            self._thread = threading.Thread(
                target=self._run, name="raw-recorder", daemon=True
            )
            self._thread.start()
            return self.status()

    def save_episode(self) -> dict[str, Any]:
        with self._operation_lock:
            episode = self._require_episode()
            with self._lock:
                self._state = "saving"
            self._stop_recorder()
            failure = self._error
            try:
                for name, camera in episode.cameras.items():
                    state = camera.stop_recording(complete=True)
                    if not state.get("complete"):
                        failure = f"{name} recording incomplete: {state.get('error')}"
                if failure:
                    raise RecordingError(failure)
                episode.writer.commit()
            except BaseException:
                self._episode = None
                self._state = "error"
                raise
            self._episode = None
            self._episode_index += 1
            self._state = "ready"
            return {
                "episode": episode.index,
                "directory": str(episode.directory),
                "rows": self._rows,
                "committed": True,
            }

    def discard_episode(self, reason: str | None = None) -> dict[str, Any]:
        with self._operation_lock:
            episode = self._require_episode()
            with self._lock:
                self._state = "discarding"
            self._stop_recorder()
            for camera in episode.cameras.values():
                try:
                    camera.stop_recording(
                        complete=False, reason=reason or "discarded by operator"
                    )
                except Exception:
                    pass
            episode.writer.close()
            _write_json(
                episode.directory / "DISCARDED.json",
                {
                    "discarded": True,
                    "reason": reason or "discarded by operator",
                    "rows": self._rows,
                },
            )
            self._episode = None
            self._episode_index += 1
            self._state = "ready"
            return {"episode": episode.index, "directory": str(episode.directory)}

    def stop_session(self) -> dict[str, Any]:
        with self._operation_lock:
            if self._episode is not None:
                raise RecordingError("save or discard the active episode first")
            committed = (
                sum(
                    1 for _ in (self._session_dir / "episodes").glob("*/COMMITTED.json")
                )
                if self._session_dir is not None
                else 0
            )
            self._state = "closed"
            self._session_id = None
            self._session_dir = None
            return dict(self.status(), committed_episodes=committed)

    # ------------------------------------------------------------------- thread
    def _run(self) -> None:
        period = 1.0 / self.settings.fps
        last_sample_ns = -1
        missing_since = None
        last_camera_check = 0.0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                sample = self.motion.sample()
                if sample and sample["timestamp_ns"] > last_sample_ns:
                    if time.monotonic() - last_camera_check > 1.0:
                        self._check_cameras()
                        last_camera_check = time.monotonic()
                    self._poll_frames()
                    row = self._build_row(sample)
                    if row is None:
                        missing_since = missing_since or started
                        if started - missing_since > self.settings.max_frame_age_s:
                            raise RecordingError(
                                "no camera frame matched the robot sample"
                            )
                    else:
                        missing_since = None
                        episode = self._episode
                        if episode is None:
                            return
                        episode.writer.append(row)
                        with self._lock:
                            self._rows += 1
                        last_sample_ns = sample["timestamp_ns"]
                elif self._state == "recording":
                    missing_since = missing_since or started
                    if started - missing_since > self.settings.max_frame_age_s:
                        raise RecordingError("no fresh robot samples while recording")
            except Exception as exc:  # noqa: BLE001 - latched and surfaced by status
                with self._lock:
                    self._error = f"{type(exc).__name__}: {exc}"
                    self._state = "failed"
                return
            self._stop.wait(max(0.0, period - (time.monotonic() - started)))

    def _check_cameras(self) -> None:
        episode = self._episode
        if episode is None:
            return
        for name, camera in episode.cameras.items():
            state = camera.status()
            if state.get("recording", {}).get("state") == "failed":
                error = state["recording"].get("error")
                raise RecordingError(f"{name} failed: {error}")

    def _poll_frames(self) -> None:
        episode = self._episode
        if episode is None:
            return
        now_ns = time.monotonic_ns()
        for name, camera in episode.cameras.items():
            index = self._index[name]
            fresh = camera.frames(index["last"], 200)
            if fresh:
                index["last"] = fresh[-1]["sequence"]
                index["frames"].extend(fresh)
            horizon = now_ns - int(self.settings.max_frame_age_s * 4e9)
            index["frames"] = [
                frame
                for frame in index["frames"]
                if frame["received_monotonic_ns"] >= horizon
            ]

    def _build_row(self, sample: dict[str, Any]) -> dict[str, Any] | None:
        if sample.get("fk_error"):
            raise RecordingError(f"sample has no valid FK: {sample['fk_error']}")
        if sample.get("state_pose10") is None or sample.get("target_pose10") is None:
            raise RecordingError("sample is missing state/action pose10")
        stamp = sample["timestamp_ns"]
        episode = self._episode
        if episode is None:
            return None
        images = {}
        for name, frames in self._index.items():
            older = [
                frame
                for frame in frames["frames"]
                if frame["received_monotonic_ns"] <= stamp
            ]
            if not older:
                return None
            frame = older[-1]
            uncertainty = stamp - frame["received_monotonic_ns"]
            if uncertainty > self.settings.max_frame_age_s * 1e9:
                raise RecordingError(f"{name} frame is too old for this sample")
            for stream, key, number in (
                ("rgb", "rgb", "rgb_frame_number"),
                ("depth", "depth", "depth_frame_number"),
            ):
                images[f"{name}_{stream}"] = {
                    "path": f"{name}/{frame[key]}",
                    "timestamp_ns": frame["received_monotonic_ns"],
                    "clock_domain": "remote_monotonic",
                    "uncertainty_ns": int(max(0, uncertainty)),
                    "frame_number": frame[number],
                }
        return {
            "timestamp_ns": stamp,
            "state": list(sample["state_pose10"]),
            "action": list(sample["target_pose10"]),
            "wrench": [0.0] * 12,
            "wrench_valid": [False, False],
            "images": images,
            "joints_rad": list(sample["joints_rad"]),
            "requested_target_rad": list(sample["requested_target_rad"]),
            "target_rad": list(sample["target_rad"]),
            "closure": sample.get("closure", 0.0),
            "target_closure": sample.get("target_closure", 0.0),
            "gripper_enabled": sample.get("gripper_enabled", False),
            "gripper_feedback_time_ns": sample.get("gripper_feedback_time_ns"),
            "gripper_position_raw": sample.get("gripper_position_raw"),
            "leader_sequence": sample.get("leader_sequence"),
            "leader_source_monotonic_ns": sample.get("leader_source_monotonic_ns"),
        }

    # ------------------------------------------------------------------ helpers
    def _gripper_description(self) -> str:
        if self.motion.status().get("gripper_enabled"):
            return (
                "Robotiq measured closure / GELLO ID7 desired closure; 0=open, 1=closed"
            )
        return "disabled explicitly; closure placeholder 0.0"

    def _require_episode(self) -> _Episode:
        if self._episode is None:
            raise RecordingError("no episode is active")
        return self._episode

    def _stop_recorder(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                raise RecordingError("recorder thread did not stop")
        self._thread = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "session": self._session_id,
                "session_dir": str(self._session_dir) if self._session_dir else None,
                "task": self._task,
                "episode_index": self._episode_index,
                "active_episode": None
                if self._episode is None
                else self._episode.index,
                "state": self._state,
                "rows": self._rows,
                "error": self._error,
                "raw_fps": self.settings.fps,
            }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
