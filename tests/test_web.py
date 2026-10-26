import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from xcore_controller.web import WebControl, WebServer, WebSettings


class FakeCamera:
    def __init__(self, url):
        self.url = url

    def status(self):
        return {
            "state": "streaming",
            "frame_age_s": 0.02,
            "sequence": 10,
            "recording": {"state": "idle", "configured": True},
        }


class FakeRemote:
    def __init__(self):
        self.calls = []
        self.motion = {"armed": False, "state": "idle", "fk_error": None}
        self.recording = {
            "session": None,
            "active_episode": None,
            "state": "idle",
            "episode_index": 0,
        }
        self.block_prepare = None

    def state(self):
        return {
            "role": "remote",
            "motion_capable": True,
            "leader_age_s": 0.05,
            "motion": dict(self.motion),
            "recording": dict(self.recording),
        }

    def call(self, action, payload=None):
        self.calls.append((action, payload or {}))
        if action == "prepare" and self.block_prepare is not None:
            self.block_prepare.wait(5)
        if action == "arm":
            self.motion.update(armed=True, state="following")
        elif action == "session/start":
            self.recording.update(session="session_test", state="ready")
        elif action == "episode/start":
            self.recording.update(active_episode=0, state="recording")
        elif action == "episode/save":
            self.recording.update(active_episode=None, state="ready")
            self.recording["episode_index"] += 1
            return {"committed": True, "rows": 3}
        elif action == "episode/discard":
            self.recording.update(active_episode=None, state="ready")
        elif action == "exit":
            self.motion.update(armed=False, state="idle")
        elif action in ("stop", "shutdown"):
            self.motion.update(armed=False, state="idle")
        elif action == "session/stop":
            self.recording.update(session=None, state="closed")
            return {"committed_episodes": 1}
        return self.state()


def settings(**overrides):
    values = dict(
        controller_url="http://127.0.0.1:9012",
        cam1_url="http://127.0.0.1:8086",
        cam2_url="http://127.0.0.1:8087",
        dataset_url="http://127.0.0.1:8090/edit-dataset",
        task="task",
        allow_motion=True,
    )
    values.update(overrides)
    return WebSettings(**values)


def make():
    remote = FakeRemote()
    control = WebControl(
        settings(),
        remote=remote,
        cameras=[
            FakeCamera("http://127.0.0.1:8086"),
            FakeCamera("http://127.0.0.1:8087"),
        ],
        log=lambda *args: None,
    )
    return control, remote


def wait_job(control):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = control.state()["job"]
        if job and job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("web job did not finish")


def token(control):
    return control.confirm({"confirmed": True})["token"]


def test_start_needs_token_and_runs_in_order():
    control, remote = make()
    with pytest.raises(Exception, match="confirmation"):
        control.submit("start", {"task": "pick"})
    control.submit("start", {"task": "pick", "token": token(control)})
    job = wait_job(control)
    assert job["state"] == "ready", job
    assert [step["name"] for step in job["steps"]] == [
        "prepare",
        "arm",
        "session/start",
    ]
    assert [call[0] for call in remote.calls] == ["prepare", "arm", "session/start"]
    assert remote.recording["session"] == "session_test"


def test_duplicate_action_is_rejected_while_job_runs():
    control, remote = make()
    remote.block_prepare = threading.Event()
    control.submit("start", {"task": "pick", "token": token(control)})
    with pytest.raises(Exception, match="still running"):
        control.submit("stop", {})
    remote.block_prepare.set()
    assert wait_job(control)["state"] == "ready"


def test_record_save_and_preconditions():
    control, remote = make()
    remote.motion.update(armed=True, state="following")
    remote.recording.update(session="session_test", state="ready")
    control.submit("record-start", {})
    assert wait_job(control)["state"] == "ready"
    assert remote.recording["active_episode"] == 0
    control.submit("record-save", {})
    job = wait_job(control)
    assert job["state"] == "ready"
    assert remote.recording["active_episode"] is None
    with pytest.raises(Exception, match="no episode"):
        control.submit("record-save", {})


def test_record_discard_closes_the_episode():
    control, remote = make()
    remote.motion.update(armed=True, state="following")
    remote.recording.update(session="session_test", active_episode=0, state="recording")
    control.submit("record-discard", {"reason": "test"})
    job = wait_job(control)
    assert job["state"] == "ready", job
    assert [step["name"] for step in job["steps"]] == ["episode/discard"]
    assert remote.recording["active_episode"] is None


def test_finish_requires_episode_decision_then_exits_and_stops_session():
    control, remote = make()
    remote.motion.update(armed=True, state="following")
    remote.recording.update(session="session_test", active_episode=0, state="recording")
    with pytest.raises(Exception, match="save or discard"):
        control.submit("finish", {"token": token(control)})
    remote.recording["active_episode"] = None
    control.submit("finish", {"token": token(control)})
    job = wait_job(control)
    assert job["state"] == "ready", job
    assert [step["name"] for step in job["steps"]] == ["exit", "session/stop"]
    assert remote.motion["armed"] is False


def test_read_only_mode_blocks_motion_but_allows_state():
    control = WebControl(
        settings(allow_motion=False),
        remote=FakeRemote(),
        cameras=[
            FakeCamera("http://127.0.0.1:8086"),
            FakeCamera("http://127.0.0.1:8087"),
        ],
        log=lambda *args: None,
    )
    assert control.state()["allow_motion"] is False
    with pytest.raises(Exception, match="did not authorize"):
        control.submit("start", {"task": "x", "token": token(control)})


def test_shutdown_calls_full_remote_shutdown_once():
    control, remote = make()
    remote.motion.update(armed=True, state="following")
    control.shutdown()
    control.shutdown()
    assert [call[0] for call in remote.calls] == ["shutdown"]
    assert remote.calls[0][1] == {"mode": "zero"}


def test_page_leave_and_heartbeat_control_shutdown_window():
    control, _ = make()
    assert control.should_shutdown() is None
    control.heartbeat()
    now = time.monotonic()
    assert control.should_shutdown(now) is None
    control.leave({})
    assert control.should_shutdown(now + 1) is None
    assert control.should_shutdown(now + control.settings.close_grace_s + 1)
    control.heartbeat()
    assert control.should_shutdown(now + control.settings.close_grace_s + 2) is None


def test_http_panel_same_origin_and_confirmation():
    control, _ = make()
    server = WebServer(("127.0.0.1", 0), control)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/") as response:
            page = response.read()
            assert b"Xcore" in page
            assert b'name="viewport"' in page
            assert b"requestFullscreen" in page
            assert b"maximize" in page
        with urllib.request.urlopen(base + "/api/state") as response:
            assert json.load(response)["allow_motion"] is True
        body = json.dumps({"confirmed": True}).encode()
        request = urllib.request.Request(
            base + "/api/confirmation",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Origin": "http://evil.example",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 403
        request = urllib.request.Request(
            base + "/api/confirmation",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Origin": base,
                "Sec-Fetch-Site": "same-origin",
            },
        )
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["token"]
        for path in ("/api/heartbeat", "/api/leave"):
            request = urllib.request.Request(
                base + path,
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request) as response:
                assert json.load(response)[
                    "ok" if path.endswith("heartbeat") else "scheduled"
                ]
    finally:
        server.shutdown()
        thread.join(2)
        server.server_close()
