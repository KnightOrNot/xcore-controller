"""Read-only hardware migration and simulated watchdog endpoints.

This milestone intentionally has no real motion endpoint. Network input is raw
GELLO feedback, not a command to the SDK. A later motion implementation must
validate calibration, limits and startup alignment before enabling the worker.
"""

import fcntl
import json
import signal
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from xcore_adapters.leader import LeaderInbox


@contextmanager
def lock_device(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Sampler:
    def __init__(self, read, *, hz):
        self.read, self.hz = read, hz
        self.lock = threading.Lock()
        self.packet = None
        self.error = None
        self.stop = threading.Event()
        self.instance = uuid.uuid4().hex
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        seq = 0
        while not self.stop.is_set():
            start = time.monotonic()
            try:
                before = time.monotonic_ns()
                ticks = self.read()
                if ticks is None or any(v is None for v in ticks):
                    raise RuntimeError("GELLO read failed")
                packet = dict(
                    version=1,
                    instance=self.instance,
                    sequence=seq,
                    ticks=ticks,
                    source_monotonic_ns=time.monotonic_ns(),
                    read_started_ns=before,
                )
                with self.lock:
                    self.packet, self.error = packet, None
                seq += 1
            except Exception as e:
                with self.lock:
                    self.error = str(e)
                    self.packet = None
            self.stop.wait(max(0, 1 / self.hz - (time.monotonic() - start)))

    def status(self):
        with self.lock:
            if self.error or self.packet is None:
                raise RuntimeError(self.error or "no sample yet")
            return dict(self.packet)


class RemoteSession:
    def __init__(self, timeout, *, simulated):
        self.lock = threading.RLock()
        self.inbox = LeaderInbox(timeout)
        self.simulated = simulated
        self.observation = {}

    def call(self, command, data):
        with self.lock:
            if command == "handshake":
                self.inbox.handshake(data["instance"])
            elif command == "leader":
                # Expiry must latch before a new sample refreshes receive time.
                try:
                    self.inbox.check()
                except TimeoutError:
                    pass
                self.inbox.accept(data)
            elif command == "arm":
                if not self.simulated:
                    raise RuntimeError(
                        "hardware motion is not implemented/enabled in this milestone"
                    )
                self.inbox.arm()
            elif command == "stop":
                self.inbox.latched = True
            else:
                raise ValueError("unknown command")
            return self.status()

    def status(self):
        with self.lock:
            try:
                self.inbox.check()
                stale = False
            except TimeoutError:
                stale = True
            return dict(
                role="remote",
                simulated=self.simulated,
                motion_capable=False,
                simulated_armed=not self.inbox.latched,
                leader_stale=stale,
                leader_sequence=self.inbox.sequence,
                observation=self.observation,
            )


class SdkMonitor:
    """All SDK calls, including connect/disconnect, stay in this one thread."""

    def __init__(self, session, ip, local_ip, sdk_dir, lock_path):
        self.session = session
        self.options = ip, local_ip, sdk_dir, lock_path
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from xcore_sdk_python.reader import RobotConnection

        ip, local_ip, sdk_dir, lock_path = self.options
        try:
            with (
                lock_device(lock_path),
                RobotConnection(ip, local_ip=local_ip, sdk_dir=sdk_dir) as c,
            ):
                while not self.stop.is_set():
                    stamp = time.monotonic_ns()
                    status = c.status()
                    status["remote_monotonic_ns"] = stamp
                    with self.session.lock:
                        self.session.observation = status
                    self.stop.wait(0.5)
        except Exception as e:
            with self.session.lock:
                self.session.observation = {"error": str(e)}


class RoleServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, state):
        self.state = state
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, value):
        body = json.dumps(value, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/status", "/sample"):
            return self.reply(404, {"error": "unknown endpoint"})
        try:
            self.reply(200, self.server.state.status())
        except Exception as e:
            self.reply(503, {"error": str(e)})

    def do_POST(self):
        try:
            if not isinstance(self.server.state, RemoteSession):
                raise ValueError("GELLO service is read-only")
            origin = self.headers.get("Origin")
            from urllib.parse import urlsplit

            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                return self.reply(403, {"error": "cross-origin request denied"})
            if self.headers.get_content_type() != "application/json":
                raise ValueError("expected application/json")
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= 16384:
                raise ValueError("invalid payload size")
            data = json.loads(self.rfile.read(n))
            if not isinstance(data, dict):
                raise ValueError("expected object")
            self.reply(200, self.server.state.call(self.path.strip("/"), data))
        except Exception as e:
            self.reply(409, {"error": str(e)})


def serve(state, host, port):
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("loopback only; use SSH tunnels")
    server = RoleServer((host, port), state)

    def stop(*args):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
