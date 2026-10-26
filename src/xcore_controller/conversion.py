"""Queue sealed sessions for the remote conversion environment.

The controller runtime is 3.11 and must not import LeRobot. It only invokes the
locked 3.12 dataset CLI as a background subprocess; conversion itself is the
dataset project's job queue, which survives crashes and never overwrites output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path


class ConversionScheduler:
    def __init__(
        self,
        *,
        python: str,
        dataset_root: Path,
        data_root: Path,
        enabled: bool = True,
        timeout_s: float = 3600,
        env: dict[str, str] | None = None,
    ) -> None:
        self.python = str(python)
        self.dataset_root = Path(dataset_root)
        self.data_root = Path(data_root).expanduser().resolve()
        self.enabled = bool(enabled)
        self.timeout_s = timeout_s
        self.env = dict(os.environ if env is None else env)
        # Never load CPython 3.11 vendor wheels in the 3.12 dataset environment.
        for name in ("PYTHONPATH", "PYTHONHOME"):
            self.env.pop(name, None)
        self._lock = threading.Lock()
        self._last: dict | None = None
        self._thread: threading.Thread | None = None

    def submit(self, session_dir: str | Path) -> dict:
        if not self.enabled:
            return {"scheduled": False, "reason": "conversion disabled"}
        session = Path(session_dir)
        with self._lock:
            self._last = {
                "session": str(session),
                "state": "running",
                "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "error": None,
                "log": None,
                "verified": False,
            }
            self._thread = threading.Thread(
                target=self._run, args=(session,), name="conversion", daemon=True
            )
            self._thread.start()
            return {"scheduled": True, "session": str(session)}

    def _command(self, *args: str) -> list[str]:
        return [self.python, "-m", "xcore_dataset.cli", *args]

    def _run(self, session: Path) -> None:
        log_dir = self.data_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / f"convert-{session.name}.log"
        with self._lock:
            if self._last is not None:
                self._last["log"] = str(log)
        try:
            with log.open("a", encoding="utf-8") as stream:
                queued = subprocess.run(
                    self._command("queue", str(session), "--root", str(self.data_root)),
                    cwd=self.dataset_root,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=self.env,
                )
                stream.write(queued.stdout + queued.stderr)
                stream.flush()
                if queued.returncode:
                    raise RuntimeError("queueing the session failed")
                job = json.loads(queued.stdout.strip())["result"]
                job_id = job["job_id"]
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", job_id):
                    raise RuntimeError("invalid conversion job ID")
                with self._lock:
                    self._last.update(job_id=job_id, phase="converting")
                done = subprocess.run(
                    self._command("jobs", "--root", str(self.data_root), "--run"),
                    cwd=self.dataset_root,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                    env=self.env,
                )
                stream.write(done.stdout + done.stderr)
                stream.flush()
                if done.returncode:
                    raise RuntimeError("conversion job failed")
                # jobs --run records per-job failures but can still exit 0.
                # Only this session's durable job and a verified publication
                # establish completion, never the command exit code alone.
                job = json.loads(
                    (self.data_root / "jobs" / f"{job_id}.json").read_text()
                )
                if job.get("state") != "ready":
                    raise RuntimeError(job.get("error") or "dataset was not published")
                destination = Path(job["destination"])
                if not destination.resolve().is_relative_to(self.data_root / "lerobot"):
                    raise RuntimeError("conversion destination escapes published root")
                with self._lock:
                    self._last["phase"] = "verifying"
                from xcore_dataset.integrity import verify

                verify(destination)
        except Exception as exc:  # noqa: BLE001 - reported in status
            with self._lock:
                if self._last is not None:
                    self._last["state"] = "failed"
                    self._last["error"] = f"{type(exc).__name__}: {exc}"
            return
        with self._lock:
            if self._last is not None:
                self._last["state"] = "ready"
                self._last.update(
                    verified=True,
                    phase="ready",
                    path=str(destination),
                    dataset_id=job["dataset_id"],
                    revision=job["revision"],
                )
                self._last["finished"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )

    def status(self) -> dict:
        with self._lock:
            if self._last is None:
                return {"enabled": self.enabled, "last": None}
            return dict(enabled=self.enabled, last=dict(self._last))
