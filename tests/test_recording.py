import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from xcore_controller.recording import (
    RecordingError,
    RecordingSettings,
    SessionRecorder,
)


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for recorder")
        time.sleep(0.01)


class FakeMotion:
    settings = SimpleNamespace(ip="127.0.0.1", calibration="/tmp/calib.json")

    def status(self):
        return {"armed": True, "fk_error": None}

    def sample(self):
        pose = [0.1, 0.2, 0.3, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        return {
            "timestamp_ns": time.monotonic_ns(),
            "joints_rad": [0.1] * 6,
            "requested_target_rad": [0.11] * 6,
            "target_rad": [0.11] * 6,
            "state_pose10": pose,
            "target_pose10": pose,
            "closure": 0.0,
            "target_closure": 0.0,
            "leader_sequence": 1,
            "leader_source_monotonic_ns": time.monotonic_ns(),
            "fk_error": None,
        }


class FakeCamera:
    def __init__(self, url, directory):
        self.url = url
        self.directory: Path | None = None
        self.number = 0
        self.failed = False

    def status(self):
        state = "failed" if self.failed else "recording"
        return {
            "state": "streaming",
            "metadata": {
                "device": {"serial_number": "TEST"},
                "depth_scale_m_per_unit": 0.001,
                "color_intrinsics": {"width": 8, "height": 8, "fx": 5, "fy": 5},
                "depth_intrinsics": {"width": 8, "height": 8, "fx": 5, "fy": 5},
                "depth_to_color": {"rotation": np.eye(3).ravel().tolist()},
                "configuration": {"serial": "TEST"},
            },
            "recording": {
                "state": state,
                "error": "sensor lost" if self.failed else None,
            },
        }

    def ensure_streaming(self, timeout=20):
        return self.status()

    def start_recording(self, directory, session, episode):
        self.directory = Path(directory)
        (self.directory / "rgb").mkdir(parents=True)
        (self.directory / "depth").mkdir()
        return {"state": "recording"}

    def stop_recording(self, *, complete=True, reason=None):
        return {"complete": complete and not self.failed, "error": None}

    def frames(self, after=-1, limit=200):
        if self.directory is None or self.number <= after:
            return []
        index = self.number
        self.number += 1
        name = f"{index:06d}.png"
        Image.fromarray(np.full((8, 8, 3), 40, np.uint8)).save(
            self.directory / "rgb" / name
        )
        Image.fromarray(np.full((8, 8), 1500, np.uint16)).save(
            self.directory / "depth" / name
        )
        return [
            {
                "sequence": index,
                "rgb": f"rgb/{name}",
                "depth": f"depth/{name}",
                "rgb_frame_number": index,
                "depth_frame_number": index + 100,
                "received_monotonic_ns": time.monotonic_ns() - 100_000_000,
            }
        ]


def make(tmp_path):
    cameras = {}

    def factory(url):
        camera = cameras.setdefault(url, FakeCamera(url, tmp_path))
        return camera

    recorder = SessionRecorder(
        RecordingSettings(
            raw_root=str(tmp_path / "raw"),
            task="test",
            fps=30,
            max_frame_age_s=2.0,
        ),
        FakeMotion(),
        camera_factory=factory,
    )
    return recorder, cameras


def test_episode_commits_with_two_lossless_cameras(tmp_path):
    recorder, cameras = make(tmp_path)
    recorder.start_session("pick and place")
    recorder.start_episode()
    wait_for(lambda: recorder.status()["rows"] >= 3)
    result = recorder.save_episode()
    assert result["committed"] is True
    directory = Path(result["directory"])
    commit = json.loads((directory / "COMMITTED.json").read_text())
    assert commit["frames"] == result["rows"]
    assert (directory / "samples.jsonl").is_file()
    assert not (directory / "samples.jsonl.partial").exists()
    rows = [
        json.loads(line)
        for line in (directory / "samples.jsonl").read_text().splitlines()
    ]
    assert len(rows) == result["rows"]
    for row in rows:
        assert set(row["images"]) == {
            "cam1_rgb",
            "cam1_depth",
            "cam2_rgb",
            "cam2_depth",
        }
        for frame in row["images"].values():
            assert frame["clock_domain"] == "remote_monotonic"
            assert (directory / frame["path"]).is_file()
    depth = np.asarray(Image.open(directory / rows[0]["images"]["cam1_depth"]["path"]))
    assert depth.dtype == np.uint16
    assert len(cameras) == 2
    assert json.loads((directory / "manifest.json").read_text())["simulated"] is False
    recorder.stop_session()


def test_camera_failure_prevents_commit(tmp_path):
    recorder, cameras = make(tmp_path)
    recorder.start_session()
    recorder.start_episode()
    wait_for(lambda: recorder.status()["rows"] >= 1)
    next(iter(cameras.values())).failed = True
    wait_for(lambda: recorder.status()["state"] == "failed", timeout=4)
    with pytest.raises(RecordingError):
        recorder.save_episode()
    directory = next((tmp_path / "raw").rglob("episode_*"))
    assert (directory / "samples.jsonl.partial").exists()
    assert not (directory / "COMMITTED.json").exists()


def test_episode_requires_armed_follow(tmp_path):
    class Disarmed(FakeMotion):
        def status(self):
            return {"armed": False, "fk_error": None}

    recorder = SessionRecorder(
        RecordingSettings(raw_root=str(tmp_path / "raw")),
        Disarmed(),
        camera_factory=lambda url: FakeCamera(url, tmp_path),
    )
    recorder.start_session()
    with pytest.raises(RecordingError, match="armed"):
        recorder.start_episode()


def test_camera_urls_must_be_loopback():
    with pytest.raises(ValueError, match="loopback"):
        RecordingSettings(
            raw_root="/tmp/x", camera_urls=("http://192.168.2.1:8086", "http://x")
        ).validate()


def test_save_status_does_not_wait_for_file_sealing(tmp_path):
    recorder, _ = make(tmp_path)
    recorder.start_session()
    recorder.start_episode()
    wait_for(lambda: recorder.status()["rows"] >= 1)
    entered, release = threading.Event(), threading.Event()
    writer = recorder._episode.writer
    original = writer.commit
    results = []

    def slow_commit():
        entered.set()
        assert release.wait(3)
        return original()

    writer.commit = slow_commit
    save = threading.Thread(target=lambda: results.append(recorder.save_episode()))
    save.start()
    try:
        assert entered.wait(1)
        status_result = []
        status = threading.Thread(
            target=lambda: status_result.append(recorder.status())
        )
        status.start()
        status.join(0.5)
        assert not status.is_alive(), "status blocked behind file sealing"
        assert status_result[0]["state"] == "saving"
    finally:
        release.set()
        save.join(4)
    assert results[0]["committed"] is True


def test_empty_session_is_not_marked_for_conversion(tmp_path):
    recorder, _ = make(tmp_path)
    recorder.start_session()
    result = recorder.stop_session()
    assert result["committed_episodes"] == 0
    assert result["session"] is None
