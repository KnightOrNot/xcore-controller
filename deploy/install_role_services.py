#!/usr/bin/env python3
"""Install disabled user units on the remote host; never starts hardware."""

import argparse
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "tools"))
from config_defaults import load  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    roles = load().data["roles"]
    home = Path.home()
    units = home / ".config/systemd/user"
    names = [
        "xcore-controller-readonly.service",
        "xcore-controller-simulate.service",
        "xcore-dataset.service",
    ]
    if args.check_only:
        for name in names:
            print(f"{units / name}: exists={(units / name).exists()}")
        return
    if any((units / name).exists() for name in names):
        raise FileExistsError(
            "role units already exist; review deployment before replacing"
        )
    units.mkdir(parents=True, exist_ok=True)
    runtime = home / "project/xcore-runtime"
    sdk_python = home / roles["remote_python"]
    datasets = home / roles["remote_dataset_python"]
    pythonpath = ":".join(
        map(
            str,
            (
                root / "src",
                root / "xcore-sdk-python/src",
                home / "project/xcore-adapters/src",
                runtime / "vendor311",
            ),
        )
    )
    for mode in ("readonly", "simulate", "dataset"):
        if mode == "dataset":
            name = "xcore-dataset.service"
            command = (
                f"{datasets} -m xcore_dataset.cli serve "
                f"--root {home / roles['remote_data_root']}/lerobot "
                f"--port {roles['dataset_port']}"
            )
            env = (
                f"Environment=PATH={runtime}/media/bin:/usr/bin:/bin\n"
                f"Environment=LD_LIBRARY_PATH={runtime}/media/lib:"
                f"{runtime}/dataset-venv/lib/python3.12/site-packages/torch/lib"
            )
        else:
            name = f"xcore-controller-{mode}.service"
            flag = "--simulate" if mode == "simulate" else "--hardware-read-only"
            command = f"{sdk_python} -m xcore_controller.cli remote-serve {flag}"
            env = f"Environment=PYTHONPATH={pythonpath}"
        path = units / name
        if path.exists():
            raise FileExistsError(
                f"{path} exists; review before replacing a deployment"
            )
        path.write_text(
            f"[Unit]\nDescription=Xcore {mode} development service\n\n"
            f"[Service]\nType=simple\nWorkingDirectory={root}\n"
            f"Environment=PYTHONUNBUFFERED=1\n{env}\nExecStart={command}\n"
            "Restart=no\nTimeoutStopSec=15\n\n[Install]\nWantedBy=default.target\n"
        )
        print(path)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)


if __name__ == "__main__":
    main()
