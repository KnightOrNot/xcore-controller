import json
import os
import select
import shutil
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest


@pytest.fixture
def launcher(tmp_path):
    source = Path(__file__).resolve().parents[1]
    root = tmp_path / "controller with spaces"
    for directory in ("scripts", "tools", "config", ".venv/bin", "bin"):
        (root / directory).mkdir(parents=True)
    shutil.copy(source / "scripts/start_remote_record.sh", root / "scripts")
    shutil.copy(source / "tools/config_defaults.py", root / "tools")
    serial = root / "test serial"
    serial.touch()
    (root / "config/default.toml").write_text(
        "[gello]\nport = " + json.dumps(str(serial))
    )
    (root / ".venv/bin/python").symlink_to(sys.executable)

    def executable(path, body):
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    client = root / ".venv/bin/xcore-controller"
    executable(
        client,
        """import json,os,pathlib,signal,sys,time
args=sys.argv[1:]
root=pathlib.Path(os.environ['TEST_BOOT_ROOT'])
with (root/'calls').open('a') as f: f.write(json.dumps(args)+'\u005cn')
if args[0]=='serve':
    (root/(args[1]+'.pid')).write_text(str(os.getpid()))
    while True: time.sleep(1)
if args[0] in ('bridge','watch-motion'):
    while True: time.sleep(1)
if args[0]=='status':
    if (root/'session').exists():
        print(json.dumps({'motion':{'state':'following','armed':True},'recording':{'session':'s1','active_episode':None},'conversion':{'last':{'state':'ready'}}}))
    else:
        print(json.dumps({'motion':{'state':'idle','armed':False},'recording':{'session':None,'active_episode':None}}))
    sys.exit(0)
if args[0]=='command' and args[2]=='session/start':
    (root/'session').write_text('1')
if args[0]=='command' and args[2]=='shutdown':
    (root/'session').unlink(missing_ok=True)
if args[0]=='command' and args[2]=='episode/save':
    time.sleep(float(os.environ.get('TEST_SAVE_DELAY','0')))
    print(json.dumps({'committed':True, 'rows':420}))
    sys.exit(0)
if args[0]=='setup-session' and args[1] in ('controller','leader','dataset'):
    until=time.monotonic()+3
    while not (root/(args[1]+'.pid')).exists():
        if time.monotonic()>until: raise RuntimeError('missing child')
        time.sleep(.01)
print(json.dumps({'ready':True}))
""",
    )
    for name, service in (
        ("start_remote_controller.sh", "controller"),
        ("start_gello_service.sh", "leader"),
        ("start_dataset.sh", "dataset"),
    ):
        script = root / "scripts" / name
        script.write_text('#!/bin/sh\nexec "$TEST_BOOT_CLIENT" serve ' + service + "\n")
        script.chmod(0o755)
    executable(
        root / "bin/ssh",
        """import json,os,pathlib,sys
root=pathlib.Path(os.environ['TEST_BOOT_ROOT'])
data=json.dumps(['ssh', *sys.argv[1:]])
with (root/'calls').open('a') as f: f.write(data+'\u005cn')
""",
    )
    executable(
        root / "bin/curl",
        """import os,pathlib,sys
root=pathlib.Path(os.environ['TEST_BOOT_ROOT'])
url=sys.argv[-1]
name='controller' if ':9012' in url else 'leader' if ':9011' in url else 'dataset'
try:
    pid=int((root/(name+'.pid')).read_text())
    os.kill(pid,0)
except (FileNotFoundError,ProcessLookupError): sys.exit(7)
""",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("XCORE_")}
    env.update(
        TEST_BOOT_ROOT=str(root),
        TEST_BOOT_CLIENT=str(client),
        PATH=str(root / "bin") + os.pathsep + os.environ["PATH"],
    )
    return root, env


def invoke(launcher, *args, input=None):
    root, env = launcher
    result = subprocess.run(
        ["bash", str(root / "scripts/start_remote_record.sh"), *args],
        input=input,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
    return result, calls


def test_cold_check_starts_all_services_without_activation_or_motion(launcher):
    root, _ = launcher
    result, calls = invoke(launcher, "--check-only")
    assert result.returncode == 0, result.stdout + result.stderr
    services = [c[1] for c in calls if c[0] == "setup-session"]
    assert services == ["controller", "gripper", "leader", "cameras", "dataset"]
    assert not any("--activate" in c or c[0] == "command" for c in calls)
    for path in root.glob("*.pid"):
        with pytest.raises(ProcessLookupError):
            os.kill(int(path.read_text()), 0)


def test_existing_local_services_are_reused_and_preserved(launcher):
    root, env = launcher
    children = [
        subprocess.Popen(
            [str(root / ".venv/bin/xcore-controller"), "serve", name], env=env
        )
        for name in ("controller", "leader", "dataset")
    ]
    try:
        deadline = time.monotonic() + 3
        while len(list(root.glob("*.pid"))) != 3:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        result, calls = invoke(launcher, "--check-only")
        assert result.returncode == 0, result.stdout + result.stderr
        assert sum(c[0] == "serve" for c in calls) == 3
        assert all(c.poll() is None for c in children)
    finally:
        for child in children:
            child.terminate()
            child.wait(timeout=3)


def test_one_confirmation_precedes_activation_prepare_and_arm(launcher):
    result, calls = invoke(launcher, "--enable-motion", input="y\nq")
    assert result.returncode == 0, result.stdout + result.stderr
    activation = next(i for i, c in enumerate(calls) if "--activate" in c)
    actions = [(i, c[2]) for i, c in enumerate(calls) if c[0] == "command"]
    assert activation < next(i for i, a in actions if a == "prepare")
    assert [a for _, a in actions] == [
        "prepare",
        "arm",
        "session/start",
        "shutdown",
    ]


@pytest.mark.parametrize("motion", [False, True])
def test_web_start_prepares_services_without_activation_or_arm(launcher, motion):
    options = ["--web"] + (["--enable-motion"] if motion else [])
    result, calls = invoke(launcher, *options, input="")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any("--activate" in c or c[0] == "command" for c in calls)
    panel = next(c for c in calls if c[0] == "web")
    assert ("--allow-motion" in panel) is motion
    assert "输入 y" not in result.stdout
    assert "尚未进入跟随" in result.stdout


def test_cancel_does_not_activate_or_move(launcher):
    result, calls = invoke(launcher, "--enable-motion", input="n\n")
    assert result.returncode == 1
    assert not any("--activate" in c or c[0] == "command" for c in calls)


def test_tty_save_immediate_feedback_and_queued_r_without_enter(launcher):
    root, env = launcher
    env["TEST_SAVE_DELAY"] = "0.8"
    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    process = subprocess.Popen(
        ["bash", str(root / "scripts/start_remote_record.sh"), "--enable-motion"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
    )
    output = bytearray()
    offset = 0

    def until(text, timeout=5):
        nonlocal offset
        marker = text.encode()
        deadline = time.monotonic() + timeout
        while True:
            position = output.find(marker, offset)
            if position >= 0:
                offset = position + len(marker)
                return
            if time.monotonic() > deadline:
                raise AssertionError(output.decode(errors="replace"))
            if select.select([master], [], [], 0.05)[0]:
                output.extend(os.read(master, 65536))

    try:
        until("输入 y 继续")
        os.write(master, b"y\n")
        until("会话已创建")
        os.write(master, b"r")  # No Enter: terminal must handle one key immediately.
        until("开始记录。")
        os.write(master, b"s")
        until("[记录] 正在保存", timeout=0.6)
        os.write(master, b"ssdr")  # Repeated S/D while busy, then one explicit R.
        until("[记录] 保存完成。")
        until("开始记录。")
        os.write(master, b"q")
        process.wait(timeout=5)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
        calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
        actions = [c[2] for c in calls if c[0] == "command"]
        assert actions.count("episode/start") == 2
        assert actions.count("episode/save") == 1
        assert "没有活动 episode" not in output.decode(errors="replace")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)
