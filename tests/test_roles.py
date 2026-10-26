import threading
import time

import pytest

from xcore_controller.cli import request
from xcore_controller.roles import RemoteSession, RoleServer, lock_device


@pytest.fixture
def endpoint():
    state = RemoteSession(0.02, simulated=True)
    server = RoleServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_network_leader_timeout_latches_before_refresh(endpoint):
    url, state = endpoint
    request(url + "/handshake", {"instance": "test"})
    p = dict(
        version=1, instance="test", sequence=0, source_monotonic_ns=1, ticks=[0] * 7
    )
    request(url + "/leader", p)
    assert request(url + "/arm", {})["simulated_armed"]
    time.sleep(0.04)
    p.update(sequence=1, source_monotonic_ns=2)
    request(url + "/leader", p)
    assert not request(url + "/status")["simulated_armed"]
    with pytest.raises(RuntimeError, match="HTTP 409"):
        request(url + "/leader", p)
    state.simulated = False
    with pytest.raises(RuntimeError, match="HTTP 409"):
        request(url + "/arm", {})


def test_lock_excludes_second_owner(tmp_path):
    with lock_device(tmp_path / "owner.lock"):
        with pytest.raises(BlockingIOError), lock_device(tmp_path / "owner.lock"):
            pass


def test_leader_ack_does_not_read_recorder_or_converter_status(endpoint):
    url, state = endpoint

    class BusyRecorder:
        def status(self):
            raise AssertionError("control input must not wait for recording status")

    state.attach_recorder(BusyRecorder())
    state.attach_conversion(BusyRecorder())
    request(url + "/handshake", {"instance": "test"})
    p = dict(
        version=1, instance="test", sequence=0, source_monotonic_ns=1, ticks=[0] * 7
    )
    assert request(url + "/leader", p) == {"accepted": True, "sequence": 0}


def test_leader_packets_continue_during_a_slow_save(endpoint):
    url, state = endpoint
    started, release = threading.Event(), threading.Event()
    status_lock = threading.Lock()

    class SlowRecorder:
        def save_episode(self):
            with status_lock:
                started.set()
                assert release.wait(3)
            return {"committed": True}

        def status(self):
            with status_lock:
                return {"state": "ready"}

    state.attach_recorder(SlowRecorder())
    request(url + "/handshake", {"instance": "test"})
    results = []
    save = threading.Thread(
        target=lambda: results.append(request(url + "/episode/save", {})),
    )
    save.start()
    try:
        assert started.wait(1)
        for sequence in range(5):
            packet = dict(
                version=1,
                instance="test",
                sequence=sequence,
                source_monotonic_ns=sequence + 1,
                ticks=[0] * 7,
            )
            reply = request(url + "/leader", packet, timeout=0.5)
            assert reply["sequence"] == sequence
    finally:
        release.set()
        save.join(3)
    assert results == [{"committed": True}]
