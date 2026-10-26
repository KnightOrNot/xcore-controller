"""SSH launchers and immutable dataset pull. No robot motion commands."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def home_path(relative):
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("remote paths must be relative to the SSH user home")
    return '"$HOME"/' + shlex.quote(relative)


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "tools"))
    from config_defaults import load

    config = load().with_environment()
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="command", required=True)
    r = subs.add_parser("remote")
    m = r.add_mutually_exclusive_group(required=True)
    m.add_argument("--simulate", action="store_true")
    m.add_argument("--hardware-read-only", action="store_true")
    m.add_argument(
        "--hardware",
        action="store_true",
        help="motion-capable remote SDK owner; arming is still explicit",
    )
    subs.add_parser("dataset")
    subs.add_parser("stop-remote")
    subs.add_parser("stop-dataset")
    pull = subs.add_parser("pull")
    pull_mode = pull.add_mutually_exclusive_group()
    pull_mode.add_argument("--pose", action="store_true")
    pull_mode.add_argument("--joints", action="store_true")
    pull.add_argument("--list", action="store_true")
    pull.add_argument("dataset", nargs="?")
    pull.add_argument("revision", nargs="?")
    a = p.parse_args(argv)
    target = config.get("remote.camera_ssh_target")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+", target):
        raise ValueError("invalid SSH target")
    roles = config.data["roles"]
    ssh = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"ConnectTimeout={config.get('timeouts.ssh_connect_s')}",
    ]
    if a.command in ("stop-remote", "stop-dataset"):
        names = (
            "xcore-controller-readonly.service "
            "xcore-controller-simulate.service "
            "xcore-controller-hardware.service"
            if a.command == "stop-remote"
            else "xcore-dataset.service"
        )
        subprocess.run(ssh + [target, "systemctl --user stop " + names], check=True)
        return
    if a.command == "pull" and a.list:
        dataset_python = "$HOME/" + roles["remote_dataset_python"]
        data_root = '"$HOME"/' + shlex.quote(roles["remote_data_root"])
        remote = (
            'cd "$HOME"/project/xcore-dataset && '
            f"{dataset_python} -m xcore_dataset.cli datasets --root {data_root}"
        )
        result = subprocess.run(
            ssh + [target, remote], check=True, capture_output=True, text=True
        )
        print(result.stdout, end="")
        return
    if a.command == "pull":
        if a.dataset is None or a.revision is None:
            raise ValueError("pull requires DATASET_ID and REVISION, or --list")
        expected_representation = "joints" if a.joints else "pose10"
        for value in (a.dataset, a.revision):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
                raise ValueError("invalid dataset/revision ID")
        base = root / config.get("recording.lerobot_data_root") / a.dataset
        final = base / a.revision
        partial = base / (a.revision + ".partial")
        if any(p.is_symlink() for p in (base, final, partial)):
            raise ValueError("local dataset directories must not be symlinks")
        dataset_project = root / "xcore-dataset"
        os.environ.setdefault("PYTHONPATH", str(dataset_project / "src"))
        sys.path.insert(0, str(dataset_project / "src"))
        from xcore_dataset.integrity import verify
        from xcore_dataset.published import detect_representation

        def check_representation(path):
            actual = detect_representation(path)
            if actual != expected_representation:
                raise RuntimeError(
                    f"representation mismatch: requested {expected_representation}, "
                    f"payload is {actual}; partial data kept for inspection"
                )
            return actual

        if final.exists():
            verify(final)
            actual = check_representation(final)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "already_present": str(final),
                        "representation": actual,
                    }
                )
            )
            return
        partial.mkdir(parents=True, exist_ok=True)
        remote = (
            roles["remote_data_root"] + "/lerobot/" + a.dataset + "/" + a.revision + "/"
        )
        home_path(remote)
        subprocess.run(
            [
                "rsync",
                "-a",
                "--partial",
                "--partial-dir=.rsync-partial",
                "-e",
                shlex.join(ssh),
                target + ":" + remote,
                str(partial) + "/",
            ],
            check=True,
        )
        verify(partial)
        actual = check_representation(partial)
        python = dataset_project / ".venv/bin/python"
        subprocess.run(
            [
                str(python),
                "-m",
                "xcore_dataset.cli",
                "verify",
                str(partial),
                "--readback",
            ],
            check=True,
        )
        partial.rename(final)
        print(
            json.dumps(
                {"ok": True, "path": str(final), "representation": actual}
            )
        )
        return
    if a.command == "remote":
        port = roles["controller_port"]
        if a.simulate:
            unit = "xcore-controller-simulate.service"
        elif a.hardware:
            unit = "xcore-controller-hardware.service"
        else:
            unit = "xcore-controller-readonly.service"
        others = [
            name
            for name in (
                "xcore-controller-readonly.service",
                "xcore-controller-simulate.service",
                "xcore-controller-hardware.service",
            )
            if name != unit
        ]
        command = (
            f"! systemctl --user is-active --quiet {' '.join(others)} && "
            f"systemctl --user start {unit}"
        )
    else:
        port = roles["dataset_port"]
        command = "systemctl --user start xcore-dataset.service"
    subprocess.run(ssh + [target, command], check=True)
    if a.command == "dataset":
        from .dataset_browser import serve

        serve(root, config, ssh, target)
        return
    print(
        f"Local endpoint: http://127.0.0.1:{port}; "
        "Ctrl+C closes the tunnel; use the stop script to stop the remote service",
        flush=True,
    )
    raise SystemExit(
        subprocess.call(ssh + ["-N", "-L", f"{port}:127.0.0.1:{port}", target])
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
