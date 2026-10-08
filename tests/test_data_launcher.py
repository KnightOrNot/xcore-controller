from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "controller with spaces"
    root.mkdir()
    source = Path(__file__).resolve().parents[1] / "start_data_record.sh"
    shutil.copy(source, root)
    follow = root / "start_gello_follow.sh"
    child = root / "fake_follow.py"
    child.write_text(
        "import json, os, pathlib, signal, sys, time\n"
        "root=pathlib.Path(__file__).parent\n"
        "args=sys.argv[1:]\n"
        "(root/'args.json').write_text(json.dumps(args))\n"
        "session=root/'raw session'\n"
        "episodes=session/'episodes'; episodes.mkdir(parents=True)\n"
        "if not os.environ.get('EMPTY'):\n"
        "    (episodes/'episode_000000.jsonl').write_text('{}\\n')\n"
        "(episodes/'episode_000001.jsonl.partial').write_text('{}\\n')\n"
        "path=pathlib.Path(args[args.index('--session-path-file')+1])\n"
        "path.write_text(str(session)+'\\n')\n"
        "def stopped(*_):\n"
        "    (root/'stopped').touch(); sys.exit(143)\n"
        "signal.signal(signal.SIGTERM,stopped)\n"
        "def return_zero(*_):\n"
        "    (root/'zero_started').touch()\n"
        "    time.sleep(.15)\n"
        "    (root/'zero_finished').touch()\n"
        "    (root/'stopped').touch()\n"
        "    sys.exit(1 if os.environ.get('FAIL_ZERO') else 130)\n"
        "signal.signal(signal.SIGUSR1,return_zero)\n"
        "(root/'ready').touch()\n"
        "if os.environ.get('HOLD'):\n"
        "    while True: time.sleep(.02)\n"
        "(root/'stopped').touch()\n"
    )
    follow.write_text(
        "#!/usr/bin/env bash\nexec "
        + shlex_quote(sys.executable)
        + " "
        + shlex_quote(str(child))
        + ' "$@"\n'
    )
    binaries = root / "lerobot-converter/.venv/bin"
    binaries.mkdir(parents=True)
    converter = binaries / "python"
    converter.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "root=pathlib.Path(__file__).resolve().parents[3]\n"
        "if sys.argv[1] == '-c': sys.exit(0)\n"
        "assert sys.argv[1] == str(root/'tools/convert_cr7.py')\n"
        "assert (root/'stopped').exists(), 'converter ran before follower shutdown'\n"
        "if (root/'zero_started').exists():\n"
        "    assert (root/'zero_finished').exists(), 'converter ran before zero finished'\n"
        "(root/'conversion.json').write_text(json.dumps(sys.argv[2:]))\n"
    )
    for binary in binaries.iterdir():
        binary.chmod(0o755)
    return root


def shlex_quote(value):
    import shlex

    return shlex.quote(value)


def test_record_entry_routes_options_and_converts_after_shutdown(launcher):
    result = subprocess.run(
        [
            "bash",
            str(launcher / "start_data_record.sh"),
            "--task",
            "pick object",
            "--gripper-force",
            "30",
            "--dataset-fps",
            "25",
            "--prepare-speed",
            "50",
            "--skip-prepare",
            "--show-state",
            "--no-return-zero",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    args = json.loads((launcher / "args.json").read_text())
    assert "--enable-motion" in args
    assert args[args.index("--gripper-host") + 1] == "192.168.2.225"
    assert "--skip-prepare" in args
    assert "--show-state" in args
    assert "--no-return-zero" in args
    assert args[args.index("--prepare-speed") + 1] == "50"
    assert args[args.index("--task") + 1] == "pick object"
    conversion = json.loads((launcher / "conversion.json").read_text())
    assert conversion[-2:] == ["--fps", "25"]


@pytest.mark.parametrize("skip,empty", [(True, False), (False, True)])
def test_skip_or_no_saved_episode_never_converts(launcher, skip, empty):
    options = ["--skip-conversion"] if skip else []
    result = subprocess.run(
        ["bash", str(launcher / "start_data_record.sh"), *options],
        env={**os.environ, **({"EMPTY": "1"} if empty else {})},
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0
    assert not (launcher / "conversion.json").exists()


@pytest.mark.parametrize(
    "interrupt,zero_failure",
    [(signal.SIGINT, False), (signal.SIGTERM, False), (signal.SIGINT, True)],
)
def test_interrupt_waits_for_follow_cleanup_before_conversion(
    launcher, interrupt, zero_failure
):
    process = subprocess.Popen(
        ["bash", str(launcher / "start_data_record.sh")],
        env={
            **os.environ,
            "HOLD": "1",
            **({"FAIL_ZERO": "1"} if zero_failure else {}),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 4
        while not (launcher / "ready").exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        process.send_signal(interrupt)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == (1 if zero_failure else 130), stdout + stderr
        assert (launcher / "conversion.json").exists()
        assert (launcher / "stopped").exists()
        assert (launcher / "zero_finished").exists() is (interrupt == signal.SIGINT)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
