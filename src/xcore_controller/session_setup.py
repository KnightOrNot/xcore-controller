"""Idempotent readiness checks and on-demand services for the record launcher."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


def get(url: str) -> dict:
    with build_opener(ProxyHandler({})).open(url, timeout=2) as response:
        return json.load(response)


def wait_for(read, timeout: float):
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    while True:
        try:
            result = read()
            if result is not None:
                return result
            last_error = "service has not produced usable feedback"
        except OSError as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"service readiness timed out: {last_error}")
        time.sleep(0.2)


def controller(config):
    url = f"http://127.0.0.1:{config['roles']['controller_port']}"

    def read():
        state = get(url + "/status")
        if state.get("role") != "remote" or state.get("simulated") is not False:
            raise RuntimeError(
                "controller endpoint is not the real remote hardware role"
            )
        if not state.get("motion_capable"):
            raise RuntimeError("controller is read-only; hardware role is required")
        motion, recording = state.get("motion", {}), state.get("recording", {})
        if motion.get("armed") or motion.get("state") in ("arming", "following"):
            raise RuntimeError(
                "remote following is already active; finish that session first"
            )
        if recording.get("session") or recording.get("active_episode") is not None:
            raise RuntimeError("remote recording session is already active")
        if motion.get("cleanup_fault") or motion.get("state") == "error":
            raise RuntimeError(f"controller requires recovery: {motion}")
        if motion.get("fk_error"):
            raise RuntimeError(f"FK unavailable: {motion['fk_error']}")
        if motion.get("state") == "starting" or not motion.get("kinematics"):
            return None
        if motion.get("gripper_enabled") != config["robot"]["follow_gripper"]:
            raise RuntimeError(
                "local/remote follow_gripper differ; sync remote config first"
            )
        return {"ready": True, "service": "controller", "url": url}

    return wait_for(read, config["timeouts"]["startup_ready_s"])


def leader(config):
    url = f"http://127.0.0.1:{config['roles']['gello_port']}"

    def read():
        state = get(url + "/sample")
        if state.get("version") != 1 or not isinstance(state.get("instance"), str):
            raise RuntimeError("unexpected service on the GELLO port")
        ticks = state.get("ticks")
        if not isinstance(ticks, list) or len(ticks) != 7:
            raise RuntimeError("GELLO must provide all seven channels")
        if any(type(value) is not int for value in ticks):
            raise RuntimeError("GELLO returned invalid joint feedback")
        stamp = state.get("source_monotonic_ns")
        if type(stamp) is not int or not 0 < time.monotonic_ns() - stamp < int(1e9):
            raise RuntimeError("GELLO sample is stale; check USB and servo power")
        return {"ready": True, "service": "gello", "url": url}

    return wait_for(read, config["timeouts"]["startup_ready_s"])


def gripper(config, *, activate=False):
    # These clients only use TCP; importing them never loads the robot extension.
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "xcore-sdk-python/src"))
    from xcore_sdk_python.gripper_follow import GripperFollowClient

    host = config["remote"]["gripper_host"]
    user = config["remote"]["gripper_ssh_user"]
    target = f"{user}@{host}"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*@[A-Za-z0-9][A-Za-z0-9.-]*", target):
        raise ValueError("invalid gripper SSH target")
    if activate:
        controller(config)  # Never activate/reset while another session is armed.
    subprocess.run(
        [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"ConnectTimeout={config['timeouts']['ssh_connect_s']}",
            target,
            "systemctl --user start xcore-gripper-follow.service",
        ],
        check=True,
        timeout=config["timeouts"]["startup_ready_s"],
    )
    client = GripperFollowClient(host, config["remote"]["gripper_port"], 1)
    state = wait_for(
        lambda: client.request("follow_status"), config["timeouts"]["gripper_ready_s"]
    )
    if state.get("streaming") is not True:
        raise RuntimeError("gripper service does not support continuous targets")
    if state.get("moving"):
        raise RuntimeError("gripper is already moving; wait for it to stop")
    code = state.get("status_code")
    if type(code) is not int:
        raise RuntimeError("invalid gripper activation feedback")
    position = state.get("position_raw")
    if type(position) is not int or not 0 <= position <= 255:
        raise RuntimeError("invalid measured gripper position")
    activated = code & 0x31 == 0x31
    error = state.get("stream_error")
    if error and error != "Gripper target stream timed out":
        raise RuntimeError(f"gripper requires recovery: {error}")
    if activate:
        if error:
            client.request("stop")
        if not activated:
            # The launcher has already obtained explicit on-site confirmation.
            # Activation is issued once; a client timeout never implies cancel.
            seconds = config["timeouts"]["gripper_ready_s"]
            activation = GripperFollowClient(
                host, config["remote"]["gripper_port"], seconds + 2
            )
            activation.request("activate", timeout=seconds)
        client.check()
        activated = True
    return {
        "ready": True,
        "service": "gripper",
        "activated": activated,
        "activation_required": not activated,
        "stream_reset_required": bool(error) and not activate,
    }


def cameras(config):
    root = Path(__file__).resolve().parents[2]
    for camera in ("cam1", "cam2"):
        url = config["camera"][camera + "_url"]
        port = urlsplit(url).port
        if port is None:
            raise ValueError("camera URL needs an explicit port")
        result = subprocess.run(
            [
                str(root / "scripts/start_camera.sh"),
                "preview",
                "--camera",
                camera,
                "--no-open",
                "--local-port",
                str(port),
                "--remote-port",
                str(port),
            ],
            timeout=config["timeouts"]["startup_ready_s"] * 2,
            capture_output=True,
            text=True,
        )
        log_dir = Path(os.environ.get("XCORE_SESSION_LOG_DIR", root / "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / f"{camera}-startup.log"
        log.write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(
                f"{camera} startup failed; see {log}: "
                + (result.stderr or result.stdout)[-1500:]
            )

        def read(url=url):
            state = get(url + "/api/status")
            if state.get("service") != "camera-realsense-d435i":
                raise RuntimeError("unexpected camera service")
            if state.get("recording", {}).get("state") == "recording":
                raise RuntimeError("camera is already recording another episode")
            if state.get("state") == "error":
                raise RuntimeError(f"camera failed: {state.get('error')}")
            if state.get("state") != "streaming" or state.get("sequence", -1) < 0:
                return None
            age = state.get("frame_age_s")
            if age is None or age > config["recording"]["camera_max_frame_age_s"]:
                return None
            if not state.get("recording", {}).get("configured"):
                raise RuntimeError("camera lossless record_root is not configured")
            return state

        wait_for(read, config["timeouts"]["startup_ready_s"])
        print(f"{camera} RGBD ready: {url}", flush=True)
    return {"ready": True, "service": "cameras", "count": 2}


def dataset(config):
    from .dataset_browser import browser_entry_url

    # A local browser can outlive collection cleanup, which stops the remote
    # dataset unit. A healthy proxy process does not prove its upstream is up.
    target = config["remote"]["camera_ssh_target"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+", target):
        raise ValueError("invalid dataset SSH target")
    subprocess.run(
        [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"ConnectTimeout={config['timeouts']['ssh_connect_s']}",
            target,
            "systemctl --user start xcore-dataset.service",
        ],
        check=True,
        timeout=config["timeouts"]["startup_ready_s"],
    )
    url = f"http://127.0.0.1:{config['roles']['dataset_port']}"

    def read():
        state = get(url + "/api/datasets")
        if not isinstance(state.get("datasets"), list):
            raise RuntimeError("unexpected service on the dataset port")
        return {
            "ready": True,
            "service": "dataset",
            "url": browser_entry_url(url + "/edit-dataset"),
        }

    return wait_for(read, config["timeouts"]["startup_ready_s"])
