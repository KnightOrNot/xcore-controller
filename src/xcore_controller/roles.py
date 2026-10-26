"""GELLO input and remote role endpoints with independent motion/recording owners."""

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
        self.motion = None
        self.recorder = None
        self.conversion = None

    def attach_motion(self, motion):
        self.motion = motion

    def attach_recorder(self, recorder):
        self.recorder = recorder

    def attach_conversion(self, conversion):
        self.conversion = conversion

    def call(self, command, data):
        # Leader state is small and lock-protected; motion commands are executed
        # outside this lock because their worker thread also reads the inbox.
        if command == "handshake":
            with self.lock:
                self.inbox.handshake(data["instance"])
                return {"accepted": True, "instance": self.inbox.instance}
        elif command == "leader":
            with self.lock:
                # Expiry must latch before a new sample refreshes receive time.
                try:
                    self.inbox.check()
                except TimeoutError:
                    pass
                self.inbox.accept(data)
                # Never read recorder/converter status on the control-data path:
                # sealing an episode can take seconds, independently of motion.
                return {"accepted": True, "sequence": self.inbox.sequence}
        elif command == "arm":
            if self.motion is not None:
                return self.motion.arm()
            if not self.simulated:
                raise RuntimeError("hardware motion is not enabled for this role")
            with self.lock:
                self.inbox.arm()
        elif command == "capture-start":
            if self.motion is None:
                raise RuntimeError("pose capture requires the motion worker")
            return self.motion.capture_start()
        elif command == "pose":
            if self.motion is None:
                raise RuntimeError("pose readback requires the motion worker")
            return self.motion.pose()
        elif command == "prepare":
            if self.motion is None:
                raise RuntimeError("preparation requires the motion worker")
            return self.motion.prepare()
        elif command == "return":
            if self.motion is None:
                raise RuntimeError("return motion requires the motion worker")
            return self.motion.return_to(data.get("mode"))
        elif command == "shutdown":
            result = {}
            if self.recorder is not None:
                status = self.recorder.status()
                if status.get("active_episode") is not None:
                    result["episode"] = self.recorder.discard_episode(
                        "controller shutdown"
                    )
                if status.get("session"):
                    session_dir = status.get("session_dir")
                    stopped = self.recorder.stop_session()
                    result["session"] = stopped
                    if (
                        session_dir
                        and self.conversion is not None
                        and stopped.get("committed_episodes", 0)
                    ):
                        result["conversion"] = self.conversion.submit(session_dir)
            if self.motion is not None:
                result["motion"] = self.motion.shutdown(data.get("mode"))
            return result
        elif command == "stop":
            if self.motion is not None:
                self.motion.disarm()
            with self.lock:
                self.inbox.latched = True
        elif command == "exit":
            if self.motion is None:
                raise RuntimeError("exit requires the motion worker")
            self.motion.disarm()
            return self.motion.return_to(data.get("mode"))
        elif command in (
            "session/start",
            "session/stop",
            "episode/start",
            "episode/save",
            "episode/discard",
        ):
            if self.recorder is None:
                raise RuntimeError("recording is not enabled for this role")
            if command == "session/start":
                return self.recorder.start_session(data.get("task"))
            if command == "session/stop":
                session_dir = self.recorder.status()["session_dir"]
                result = self.recorder.stop_session()
                if session_dir and self.conversion is not None:
                    result["conversion"] = (
                        self.conversion.submit(session_dir)
                        if result.get("committed_episodes", 0)
                        else {"scheduled": False, "reason": "no sealed episodes"}
                    )
                return result
            if command == "episode/start":
                return self.recorder.start_episode()
            if command == "episode/save":
                return self.recorder.save_episode()
            return self.recorder.discard_episode(data.get("reason"))
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
            age = None
            if self.inbox.received_ns:
                age = (time.monotonic_ns() - self.inbox.received_ns) / 1e9
            result = dict(
                role="remote",
                simulated=self.simulated,
                motion_capable=self.motion is not None,
                simulated_armed=not self.inbox.latched,
                leader_stale=stale,
                leader_age_s=age,
                leader_sequence=self.inbox.sequence,
                observation=self.observation,
            )
        if self.motion is not None:
            result["motion"] = self.motion.status()
        if self.recorder is not None:
            result["recording"] = self.recorder.status()
        if self.conversion is not None:
            result["conversion"] = self.conversion.status()
        return result


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
            print(
                f"[http] {self.path}: {type(e).__name__}: {e}",
                flush=True,
            )
            self.reply(409, {"error": f"{type(e).__name__}: {e}"})


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
