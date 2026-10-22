import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


def request(url, data=None):
    r = Request(
        url,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(r, timeout=2) as f:
        return json.load(f)


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
    b = subs.add_parser("bridge")
    b.add_argument("--leader-url", required=True)
    b.add_argument("--remote-url", required=True)
    s = subs.add_parser("status")
    s.add_argument("url")
    a = p.parse_args(argv)
    sys.path.insert(0, str(root / "tools"))
    from config_defaults import load

    config = load(a.config).with_environment().data
    roles = config["roles"]
    if a.command == "status":
        print(json.dumps(request(a.url + "/status"), ensure_ascii=False, indent=2))
        return
    if a.command == "bridge":
        instance = None
        seq = -1
        while True:
            try:
                sample = request(a.leader_url + "/sample")
                if sample["instance"] != instance:
                    request(
                        a.remote_url + "/handshake", {"instance": sample["instance"]}
                    )
                    instance, seq = sample["instance"], -1
                if sample["sequence"] > seq:
                    request(a.remote_url + "/leader", sample)
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
        state = RemoteSession(roles["leader_timeout_s"], simulated=a.simulate)
        monitor = None
        if not a.simulate:
            sys.path.insert(0, str(root / "xcore-sdk-python/src"))
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


def main(argv=None):
    try:
        return _main(argv)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
