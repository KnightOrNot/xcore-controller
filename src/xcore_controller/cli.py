import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# Motion commands legitimately take minutes; the old fixed 2 s timeout made a
# running prepare look like a failure and aborted the launcher before arm.
COMMAND_TIMEOUTS = {
    "prepare": 900,
    "exit": 900,
    "return": 900,
    "arm": 60,
    "stop": 60,
    "pose": 15,
    "capture-start": 15,
    "episode/start": 90,
    "episode/save": 600,
    "episode/discard": 90,
    "session/start": 30,
    "session/stop": 90,
}


def request(url, data=None, timeout=2):
    r = Request(
        url,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(r, timeout=timeout) as f:
            return json.load(f)
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"{url}: HTTP {exc.code}: {body}") from exc
    except TimeoutError as exc:
        raise TimeoutError(
            f"{url}: no response within {timeout}s. The command may still be "
            "running on the remote controller; check `status` before retrying."
        ) from exc


def _main(argv=None):
    root = Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser(
        description="Local GELLO / remote read-only controller migration"
    )
    p.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("XCORE_CONFIG", root / "config/default.toml")),
    )
    subs = p.add_subparsers(dest="command", required=True)
    g = subs.add_parser("gello-serve")
    g.add_argument("--simulate", action="store_true")
    r = subs.add_parser("remote-serve")
    mode = r.add_mutually_exclusive_group(required=True)
    mode.add_argument("--simulate", action="store_true")
    mode.add_argument("--hardware-read-only", action="store_true")
    mode.add_argument(
        "--hardware",
        action="store_true",
        help="SDK owner with explicit arm; motion still requires /arm",
    )
    r.add_argument("--calib", type=Path)
    r.add_argument("--sdk-config", type=Path)
    r.add_argument("--max-speed-deg", type=float)
    r.add_argument("--prepare-speed", type=float)
    r.add_argument("--return-mode", choices=("start", "zero", "none"))
    r.add_argument("--data-root", type=Path)
    r.add_argument("--raw-fps", type=float)
    r.add_argument("--task")
    b = subs.add_parser("bridge")
    b.add_argument("--leader-url", required=True)
    b.add_argument("--remote-url", required=True)
    s = subs.add_parser("status")
    s.add_argument("url")
    c = subs.add_parser("command", help="send one control request to a role")
    c.add_argument("url")
    c.add_argument(
        "action",
        choices=(
            "arm",
            "prepare",
            "stop",
            "exit",
            "capture-start",
            "pose",
            "session/start",
            "session/stop",
            "episode/start",
            "episode/save",
            "episode/discard",
        ),
    )
    c.add_argument("--return-mode", choices=("start", "zero", "none"))
    c.add_argument("--task")
    c.add_argument("--reason")
    a = p.parse_args(argv)
    sys.path.insert(0, str(root / "tools"))
    from config_defaults import load

    config = load(a.config).with_environment().data
    roles = config["roles"]
    if a.command == "status":
        print(json.dumps(request(a.url + "/status"), ensure_ascii=False, indent=2))
        return
    if a.command == "command":
        payload = {}
        if a.action == "exit" and a.return_mode:
            payload["mode"] = a.return_mode
        if a.action == "session/start" and a.task:
            payload["task"] = a.task
        if a.action == "episode/discard" and a.reason:
            payload["reason"] = a.reason
        print(
            json.dumps(
                request(
                    a.url + "/" + a.action,
                    payload,
                    timeout=COMMAND_TIMEOUTS.get(a.action, 30),
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if a.command == "bridge":
        instance = None
        seq = -1
        while True:
            try:
                sample = request(a.leader_url + "/sample")
                if sample["instance"] != instance:
                    request(
                        a.remote_url + "/handshake",
                        {"instance": sample["instance"]},
                        timeout=5,
                    )
                    instance, seq = sample["instance"], -1
                if sample["sequence"] > seq:
                    # A slow post must not kill the bridge; the remote has its
                    # own stale timeout and latches until an explicit re-arm.
                    request(a.remote_url + "/leader", sample, timeout=5)
                    seq = sample["sequence"]
            except Exception:
                # Never retry a queued old motion target after a broken link.
                instance, seq = None, -1
                raise
            time.sleep(1 / roles["leader_poll_hz"])
    from .roles import RemoteSession, Sampler, SdkMonitor, lock_device, serve

    if a.command == "gello-serve":
        import contextlib

        arm = None
        with contextlib.ExitStack() as stack:
            if a.simulate:

                def read():
                    return [2048] * 7
            else:
                stack.enter_context(lock_device(root / "xcore-sdk-python/.follow.lock"))
                # Reuse the proven read-only transport; no vendor extension import.
                sys.path.insert(0, str(root / "xcore-sdk-python/src"))
                from xcore_sdk_python.dynamixel_reader import TeachArm

                arm = TeachArm(config["gello"]["port"], 57600, (1, 2, 3, 4, 5, 6), 7)
                stack.callback(arm.close)

                def read():
                    ticks = arm.read_ticks()
                    return (
                        None if ticks is None else [ticks.get(i) for i in range(1, 8)]
                    )

            sampler = Sampler(read, hz=roles["leader_poll_hz"])
            sampler.thread.start()
            try:
                serve(sampler, roles["bind_host"], roles["gello_port"])
            finally:
                sampler.stop.set()
                sampler.thread.join(3)
    else:
        # In hardware mode the leader crosses HTTP/SSH; the read-only status
        # latch (0.5 s) is far too tight for the RT stale watchdog.
        leader_timeout = roles["leader_timeout_s"]
        if getattr(a, "hardware", False):
            leader_timeout = max(
                leader_timeout, config["robot"]["remote_stale_timeout_s"]
            )
        state = RemoteSession(leader_timeout, simulated=a.simulate)
        monitor = motion = None
        if not a.simulate:
            sys.path.insert(0, str(root / "xcore-sdk-python/src"))
            if a.hardware:
                from xcore_sdk_python.configuration import load_config

                from .motion import MotionSettings, MotionWorker

                sdk_config = (
                    a.sdk_config or root / "xcore-sdk-python/config/default.toml"
                )
                sdk = load_config(sdk_config)
                calib = Path(a.calib or sdk.calibration.file)
                if not calib.is_absolute():
                    # SDK-relative file, exactly like the direct follow CLI.
                    calib = Path(sdk_config).resolve().parent.parent / calib
                # The leader arrives over HTTP, not a local serial loop; give the
                # server threads more GIL slices and tolerate short stalls.
                sys.setswitchinterval(0.0005)
                settings = MotionSettings(
                    ip=config["robot"]["ip"],
                    local_ip=roles["remote_local_ip"],
                    lock_path=str(root / "xcore-sdk-python/.follow.lock"),
                    calibration=str(calib),
                    max_speed_deg=a.max_speed_deg
                    if a.max_speed_deg is not None
                    else config["robot"]["follow_max_speed_deg"],
                    accel_deg_s2=sdk.server.accel_deg_s2,
                    control_hz=sdk.server.state_hz,
                    stale_timeout_s=max(
                        sdk.server.stale_timeout_s,
                        config["robot"]["remote_stale_timeout_s"],
                    ),
                    gate_deg=sdk.server.gate_deg,
                    prepare_speed=a.prepare_speed
                    if a.prepare_speed is not None
                    else config["robot"]["prepare_speed"],
                    prepare_samples=sdk.calibration.samples,
                    prepare_interval_s=sdk.calibration.interval_s,
                    prepare_max_step_deg=sdk.prepare.max_step_deg,
                    prepare_tolerance_deg=sdk.prepare.tolerance_deg,
                    prepare_timeout_s=sdk.prepare.motion_timeout_s,
                    return_speed=sdk.return_.speed,
                    return_max_step_deg=sdk.return_.max_step_deg,
                    return_tolerance_deg=sdk.return_.tolerance_deg,
                    return_timeout_s=sdk.return_.motion_timeout_s,
                    return_mode=a.return_mode or config["robot"]["return_mode"],
                )
                motion = MotionWorker(settings, state.inbox, state.lock)
                state.attach_motion(motion)
                sys.path.insert(0, str(root / "xcore-dataset/src"))
                from .recording import RecordingSettings, SessionRecorder

                recorder = SessionRecorder(
                    RecordingSettings(
                        raw_root=str(
                            a.data_root
                            or Path.home() / roles["remote_data_root"] / "raw"
                        ),
                        task=a.task or config["recording"]["task"],
                        fps=a.raw_fps or config["recording"]["raw_fps"],
                        camera_urls=(
                            config["camera"]["cam1_url"],
                            config["camera"]["cam2_url"],
                        ),
                        max_frame_age_s=config["recording"]["camera_max_frame_age_s"],
                    ),
                    motion,
                )
                state.attach_recorder(recorder)
                from .conversion import ConversionScheduler

                data_root = Path(recorder.settings.raw_root).expanduser().resolve()
                dataset_python = Path.home() / roles["remote_dataset_python"]
                runtime = dataset_python.parents[2]
                environment = dict(os.environ)
                environment["PATH"] = (
                    f"{runtime}/media/bin:" + environment.get("PATH", "/usr/bin:/bin")
                )
                environment["LD_LIBRARY_PATH"] = (
                    f"{runtime}/media/lib:"
                    f"{runtime}/dataset-venv/lib/python3.12/site-packages/torch/lib"
                )
                state.attach_conversion(
                    ConversionScheduler(
                        python=dataset_python,
                        dataset_root=root / "xcore-dataset",
                        data_root=data_root.parent,
                        enabled=config["recording"]["convert"],
                        env=environment,
                    )
                )
            else:
                monitor = SdkMonitor(
                    state,
                    config["robot"]["ip"],
                    roles["remote_local_ip"],
                    None,
                    root / "xcore-sdk-python/.follow.lock",
                )
                monitor.thread.start()
        try:
            serve(state, roles["bind_host"], roles["controller_port"])
        finally:
            if monitor:
                monitor.stop.set()
                monitor.thread.join(5)
            if motion:
                motion.close()


def main(argv=None):
    try:
        return _main(argv)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
