import os
import shutil
import subprocess
import sys
from pathlib import Path

from xcore_controller import cli
from xcore_controller.conversion import ConversionScheduler


def test_watcher_surfaces_remote_abort_in_the_client_terminal(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "request",
        lambda *a, **kw: {
            "motion": {
                "armed": False,
                "state": "stopped",
                "abort_reason": "gripper feedback is stale",
            },
        },
    )
    assert cli.main(["watch-motion", "http://127.0.0.1:9012"]) == 1
    assert "gripper feedback is stale" in capsys.readouterr().err


def test_dataset_subprocess_does_not_inherit_311_extensions(tmp_path):
    environment = {
        "PYTHONPATH": "/runtime/vendor311",
        "PYTHONHOME": "/runtime/python311",
        "LD_LIBRARY_PATH": "/runtime/media/lib",
        "PATH": "/runtime/media/bin",
    }
    scheduler = ConversionScheduler(
        python="python3.12",
        dataset_root=Path("."),
        data_root=tmp_path,
        env=environment,
    )
    assert "PYTHONPATH" not in scheduler.env
    assert "PYTHONHOME" not in scheduler.env
    assert scheduler.env["LD_LIBRARY_PATH"] == environment["LD_LIBRARY_PATH"]
    assert environment["PYTHONPATH"] == "/runtime/vendor311"


def test_launcher_detects_background_failure_without_keyboard_input(tmp_path):
    root = tmp_path / "controller with spaces"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(
        Path(__file__).resolve().parents[1] / "scripts/start_remote_record.sh",
        root / "scripts/start_remote_record.sh",
    )

    def executable(path, code):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!{sys.executable}\n" + code)
        path.chmod(0o755)

    executable(
        root / "tools/config_defaults.py",
        "print('''"
        + "\n".join(
            [
                "XCORE_TASK=test",
                "XCORE_CONTROLLER_SERVICE_PORT=9012",
                "XCORE_GELLO_SERVICE_PORT=9011",
                "XCORE_RETURN_MODE=zero",
                "XCORE_FOLLOW_GRIPPER=false",
            ]
        )
        + "''')\n",
    )
    client = root / ".venv/bin/xcore-controller"
    executable(
        client,
        "import json,os,sys,time\n"
        "args=sys.argv[1:]\n"
        "if args[0]=='bridge':\n"
        "    while True: time.sleep(1)\n"
        "if args[0]=='watch-motion':\n"
        "    print('[跟随故障] injected RT failure', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "if args[0]=='command':\n"
        "    with open(os.environ['TEST_FOLLOW_CALLS'],'a') as f:\n"
        "        f.write(args[2]+'\\n')\n"
        "print(json.dumps({'ok':True}))\n",
    )
    (root / ".venv/bin/python").symlink_to(sys.executable)
    executable(
        root / "bin/uv",
        "import os,sys\n"
        f"client={str(client)!r}\n"
        "args=sys.argv[sys.argv.index('xcore-controller')+1:]\n"
        "os.execv(client,[client]+args)\n",
    )
    executable(root / "bin/curl", "raise SystemExit(0)\n")
    calls = root / "calls"
    process = subprocess.Popen(
        [
            "bash",
            str(root / "scripts/start_remote_record.sh"),
            "--enable-motion",
            "--no-auto-start",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            **os.environ,
            "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
            "TEST_FOLLOW_CALLS": str(calls),
        },
    )
    try:
        process.stdin.write("y\n")
        process.stdin.flush()  # Keep stdin open: failure must surface without a key.
        process.wait(timeout=8)
        output, errors = process.stdout.read(), process.stderr.read()
        assert process.returncode == 1, output + errors
        assert "injected RT failure" in errors
        commands = calls.read_text().splitlines()
        assert "stop" in commands and "session/stop" in commands
        assert "exit" not in commands  # No automatic return on a follow fault.
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
