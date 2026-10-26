"""Local loopback data-collection panel.

The page is a thin client over the existing remote worker API. It never opens a
second SDK session, GELLO port or camera pipeline. Long operations run in one
background job; motion needs a one-time server-side confirmation token in
addition to the browser checkbox.
"""

from __future__ import annotations

import json
import secrets
import signal
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .dataset_browser import browser_entry_url

ACTIONS = ("start", "stop", "record-start", "record-save", "record-discard", "finish")


class WebError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebSettings:
    controller_url: str
    cam1_url: str
    cam2_url: str
    dataset_url: str
    task: str = "CR7 GELLO teleoperation"
    return_mode: str = "zero"
    allow_motion: bool = False
    host: str = "127.0.0.1"
    port: int = 8095
    confirmation_ttl_s: float = 90.0
    refresh_hz: float = 2.0
    leader_max_age_s: float = 5.0
    close_grace_s: float = 8.0
    heartbeat_timeout_s: float = 120.0
    conversion_wait_s: float = 600.0

    def validate(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("the web panel must bind loopback only")
        if not 1 <= self.port <= 65535:
            raise ValueError("invalid web port")
        if self.return_mode not in ("start", "zero", "none"):
            raise ValueError("invalid return mode")
        if not 0.5 <= self.refresh_hz <= 10:
            raise ValueError("invalid refresh rate")
        if not 5 <= self.confirmation_ttl_s <= 600:
            raise ValueError("invalid confirmation lifetime")
        if not 2 <= self.close_grace_s <= 60:
            raise ValueError("invalid close grace period")
        if not 30 <= self.heartbeat_timeout_s <= 600:
            raise ValueError("invalid heartbeat timeout")
        if self.conversion_wait_s <= 0:
            raise ValueError("invalid conversion wait timeout")
        if not self.task.strip():
            raise ValueError("task must not be empty")
        for url in (self.controller_url, self.cam1_url, self.cam2_url):
            if not url.startswith("http://127.0.0.1:"):
                raise ValueError("web proxy targets must use loopback HTTP")


def _request(url: str, data: dict | None, timeout: float) -> dict:
    request = urllib.request.Request(url)
    if data is not None:
        request.data = json.dumps(data).encode()
        request.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise WebError(f"{url}: HTTP {exc.code}: {body}") from exc
    except (OSError, ValueError) as exc:
        raise WebError(f"{url}: {exc}") from exc
    if not isinstance(value, dict):
        raise WebError(f"{url}: non-object response")
    return value


class RemoteClient:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def state(self) -> dict:
        return _request(self.url + "/status", None, 2)

    def call(self, action: str, payload: dict | None = None) -> dict:
        from .cli import COMMAND_TIMEOUTS

        return _request(
            self.url + "/" + action,
            payload or {},
            COMMAND_TIMEOUTS.get(action, 30),
        )


class CameraClient:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def status(self) -> dict:
        return _request(self.url + "/api/status", None, 0.6)


def _camera_summary(name: str, client: CameraClient) -> dict:
    try:
        value = client.status()
    except Exception as exc:  # noqa: BLE001 - preview health is advisory only
        return {"name": name, "url": client.url, "error": str(exc)}
    recording = value.get("recording") or {}
    return {
        "name": name,
        "url": client.url,
        "state": value.get("state"),
        "frame_age_s": value.get("frame_age_s"),
        "sequence": value.get("sequence"),
        "observed_fps": value.get("observed_fps"),
        "recording": recording.get("state"),
        "record_configured": recording.get("configured"),
        "error": value.get("error"),
    }


class WebControl:
    def __init__(
        self,
        settings: WebSettings,
        *,
        remote: Any = None,
        cameras: Any = None,
        gripper_setup=None,
        log=print,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.remote = remote or RemoteClient(settings.controller_url)
        self.cameras = cameras or [
            CameraClient(settings.cam1_url),
            CameraClient(settings.cam2_url),
        ]
        self.log = log
        self.gripper_setup = gripper_setup
        self._lock = threading.RLock()
        self._tokens: dict[str, float] = {}
        self._job: dict | None = None
        self._thread: threading.Thread | None = None
        self._last_heartbeat: float | None = None
        self._leave_deadline: float | None = None
        self._shutdown_done = False
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="web-state"
        )

    # ------------------------------------------------------------------ state
    def state(self) -> dict:
        error = None
        try:
            remote = self.remote.state()
        except Exception as exc:  # noqa: BLE001 - page shows the failure
            remote, error = {}, str(exc)
        futures = [
            self._executor.submit(_camera_summary, f"cam{i + 1}", cam)
            for i, cam in enumerate(self.cameras)
        ]
        cameras = [future.result() for future in futures]
        with self._lock:
            job = None if self._job is None else self._job_snapshot()
        return {
            "ok": error is None,
            "error": error,
            "remote": remote,
            "cameras": cameras,
            "dataset_url": browser_entry_url(self.settings.dataset_url),
            "allow_motion": self.settings.allow_motion,
            "return_mode": self.settings.return_mode,
            "task": self.settings.task,
            "confirmation_ttl_s": self.settings.confirmation_ttl_s,
            "refresh_hz": self.settings.refresh_hz,
            "job": job,
        }

    # ----------------------------------------------------------- confirmation
    def confirm(self, payload: dict) -> dict:
        if payload.get("confirmed") is not True:
            raise WebError("motion confirmation checkbox is required")
        now = time.monotonic()
        with self._lock:
            self._tokens = {
                token: expiry for token, expiry in self._tokens.items() if expiry > now
            }
            token = secrets.token_urlsafe(24)
            self._tokens[token] = now + self.settings.confirmation_ttl_s
        return {"token": token, "expires_in_s": self.settings.confirmation_ttl_s}

    # ---------------------------------------------------------------- lifecycle
    def heartbeat(self) -> dict:
        now = time.monotonic()
        with self._lock:
            self._last_heartbeat = now
            self._leave_deadline = None
        return {"ok": True}

    def leave(self, payload: dict | None = None) -> dict:
        now = time.monotonic()
        with self._lock:
            if self._last_heartbeat is None:
                return {"scheduled": False, "reason": "no active page"}
            self._leave_deadline = now + self.settings.close_grace_s
        return {
            "scheduled": True,
            "reason": "page closed",
            "grace_s": self.settings.close_grace_s,
        }

    def should_shutdown(self, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._leave_deadline is not None and now >= self._leave_deadline:
                return "browser page closed"
            if (
                self._last_heartbeat is not None
                and now - self._last_heartbeat > self.settings.heartbeat_timeout_s
            ):
                return "browser heartbeat lost"
        return None

    def _consume(self, token: Any) -> None:
        now = time.monotonic()
        with self._lock:
            expiry = self._tokens.pop(token, None) if isinstance(token, str) else None
        if expiry is None or expiry <= now:
            raise WebError(
                "motion confirmation is missing or expired; confirm the motion "
                "range again"
            )

    def _job_snapshot(self) -> dict:
        job = dict(self._job)
        job["steps"] = [dict(step) for step in self._job["steps"]]
        return job

    # ----------------------------------------------------------------- actions
    def submit(self, action: str, payload: dict) -> dict:
        if action not in ACTIONS:
            raise WebError(f"unknown action: {action}")
        if action != "stop" and not self.settings.allow_motion:
            raise WebError("the launcher did not authorize motion (--enable-motion)")
        with self._lock:
            if self._job is not None and self._job["state"] == "running":
                raise WebError("another action is still running")
        view = self.state()
        state = view["remote"]
        conversion = (state.get("conversion") or {}).get("last") or {}
        if action != "stop" and conversion.get("state") in ("queued", "running"):
            raise WebError("数据集仍在转换、校验和发布，请等待完成后再操作")
        self._precheck(action, state, view["cameras"])
        if action in ("start", "finish"):
            self._consume(payload.get("token"))
        task = str(payload.get("task") or self.settings.task).strip()
        if action == "start" and not task:
            raise WebError("task must not be empty")
        with self._lock:
            if self._job is not None and self._job["state"] == "running":
                raise WebError("another action is still running")
            steps: list = []
            self._job = {
                "id": secrets.token_hex(8),
                "action": action,
                "state": "running",
                "started": time.time(),
                "finished": None,
                "error": None,
                "steps": steps,
            }
            job = self._job_snapshot()
            self._thread = threading.Thread(
                target=self._run,
                args=(action, task, steps, self._job["id"]),
                name="web-job",
                daemon=True,
            )
            self._thread.start()
        return job

    def _precheck(self, action: str, state: dict, cameras: list) -> None:
        motion = state.get("motion") or {}
        recording = state.get("recording") or {}
        armed = bool(motion.get("armed")) and motion.get("state") in (
            "armed",
            "arming",
            "following",
        )
        if action == "start":
            if not state.get("motion_capable"):
                raise WebError("remote role is not motion capable")
            if armed:
                raise WebError("a follow session is already armed")
            if motion.get("state") not in ("idle", "stopped"):
                raise WebError(f"cannot start while motion is {motion.get('state')}")
            for key in ("cleanup_fault", "error", "abort_reason", "fk_error"):
                if motion.get(key):
                    raise WebError(f"motion requires recovery: {motion[key]}")
            age = state.get("leader_age_s")
            if age is None or age > self.settings.leader_max_age_s:
                raise WebError("GELLO samples are stale or unavailable")
            if recording.get("session"):
                raise WebError("a recording session is already active")
            for camera in cameras:
                if camera.get("error"):
                    raise WebError(f"{camera['name']} unavailable: {camera['error']}")
                if camera.get("state") != "streaming":
                    raise WebError(f"{camera['name']} is not streaming")
                if (camera.get("frame_age_s") or 99) > 2.0:
                    raise WebError(f"{camera['name']} frames are stale")
        elif action == "record-start":
            if not armed or motion.get("state") != "following":
                raise WebError("start recording only while following is active")
            if not recording.get("session"):
                raise WebError("start a follow session before recording")
            if recording.get("active_episode") is not None:
                raise WebError("an episode is already active")
        elif action in ("record-save", "record-discard"):
            if recording.get("active_episode") is None:
                raise WebError("no episode is active")
        elif action == "finish":
            if recording.get("active_episode") is not None:
                raise WebError("save or discard the active episode first")
            if not armed and not recording.get("session"):
                raise WebError("there is no follow session to finish")

    def _run(self, action: str, task: str, steps: list, job_id: str) -> None:
        def update(**fields):
            with self._lock:
                if self._job is not None and self._job["id"] == job_id:
                    self._job.update(fields)

        def step(name: str, fn):
            with self._lock:
                steps.append({"name": name, "state": "running"})
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - surfaced in the page
                with self._lock:
                    steps[-1].update(state="failed", error=str(exc))
                raise
            with self._lock:
                steps[-1].update(state="ok")
            return result

        try:
            if action == "start":
                if self.gripper_setup is not None:
                    step("gripper", self.gripper_setup)
                step("prepare", lambda: self.remote.call("prepare"))
                step("arm", lambda: self.remote.call("arm"))
                after = self.remote.state()
                motion = after.get("motion") or {}
                if not motion.get("armed") or motion.get("state") != "following":
                    raise WebError("remote did not report an armed follow session")
                step(
                    "session/start",
                    lambda: self.remote.call("session/start", {"task": task}),
                )
            elif action == "stop":
                step("stop", lambda: self.remote.call("stop"))
            elif action == "record-start":
                step("episode/start", lambda: self.remote.call("episode/start"))
            elif action == "record-save":
                result = step("episode/save", lambda: self.remote.call("episode/save"))
                if result.get("committed") is not True:
                    raise WebError("remote did not report a committed episode")
            elif action == "record-discard":
                step(
                    "episode/discard",
                    lambda: self.remote.call(
                        "episode/discard", {"reason": "operator discard (web)"}
                    ),
                )
            elif action == "finish":
                state = self.remote.state()
                armed = bool((state.get("motion") or {}).get("armed"))
                if armed:
                    step(
                        "exit",
                        lambda: self.remote.call(
                            "exit", {"mode": self.settings.return_mode}
                        ),
                    )
                    after = self.remote.state()
                    if (after.get("motion") or {}).get("armed"):
                        raise WebError("remote is still armed after exit")
                latest = self.remote.state()
                if (latest.get("recording") or {}).get("session"):
                    stopped = step(
                        "session/stop", lambda: self.remote.call("session/stop")
                    )
                    conversion = stopped.get("conversion") or {}
                    if conversion.get("scheduled"):
                        publication = step(
                            "转换、校验并发布数据集",
                            lambda: self._wait_for_publication(conversion["session"]),
                        )
                        update(publication=publication)
        except Exception as exc:  # noqa: BLE001 - keep the failure visible
            update(
                state="failed",
                error=f"{type(exc).__name__}: {exc}",
                finished=time.time(),
            )
            self.log(f"[web] {action} failed: {exc}")
            return
        update(state="ready", finished=time.time(), steps=steps)
        self.log(f"[web] {action} finished")

    def _wait_for_publication(self, session: str) -> dict:
        deadline = time.monotonic() + self.settings.conversion_wait_s
        while True:
            conversion = (self.remote.state().get("conversion") or {}).get("last") or {}
            if conversion.get("session") != session:
                raise WebError("无法确认本次会话的转换状态，请检查远端任务")
            state = conversion.get("state")
            if state == "failed":
                raise WebError(conversion.get("error") or "数据集转换失败，未发布")
            if state == "ready":
                if not conversion.get("verified") or not conversion.get("path"):
                    raise WebError("转换未确认完整性校验和发布成功，不能报告保存完成")
                return conversion
            if state not in ("queued", "running"):
                raise WebError(f"未知转换状态：{state}")
            if time.monotonic() >= deadline:
                raise WebError("等待数据发布超时；远端可能仍在处理，完成前操作继续锁定")
            time.sleep(1 / self.settings.refresh_hz)

    # ---------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        """Full remote shutdown: discard active episode, stop session, return, power off."""
        with self._lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
        try:
            # Opening the panel only prepares services. Closing it before Start
            # must never turn the configured exit pose into a first motion.
            mode = "none"
            try:
                state = self.remote.state()
                motion = state.get("motion") or {}
                recording = state.get("recording") or {}
                if (motion.get("armed") or recording.get("session")) and not any(
                    motion.get(key)
                    for key in ("error", "abort_reason", "cleanup_fault")
                ):
                    mode = self.settings.return_mode
            except Exception:
                pass  # Unknown state permits stop/power-off, never a return move.
            result = self.remote.call("shutdown", {"mode": mode})
            self.log(f"[web] remote shutdown: {result}")
        except Exception as exc:  # noqa: BLE001 - best effort on exit
            self.log(f"[web] shutdown failed: {exc}")
            try:
                self.remote.call("stop")
            except Exception:
                pass


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Xcore 数采面板</title>
<style>
:root{color-scheme:dark;--bg:#0d1117;--panel:#161b22;--line:#30363d;--muted:#8b949e;--text:#d7dde5;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--accent:#58a6ff}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{display:flex;flex-direction:column;overflow:hidden;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{flex:0 0 52px;display:flex;align-items:center;gap:12px;padding:0 16px;background:var(--panel);border-bottom:1px solid var(--line)}
header h1{font-size:16px;margin:0;white-space:nowrap}
header .spacer{flex:1}
.badge{border:1px solid var(--line);border-radius:999px;padding:2px 9px;font-size:12px;color:var(--muted)}
.badge.on{color:var(--ok);border-color:#238636}.badge.off{color:var(--warn);border-color:#9e6a03}
main{flex:1;min-height:0;display:grid;grid-template-columns:370px minmax(0,1fr);gap:12px;padding:12px}
body.focus main{grid-template-columns:minmax(0,1fr)}
body.focus aside{display:none}
aside{min-height:0;overflow:auto;display:flex;flex-direction:column;gap:12px;padding-right:2px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;flex:0 0 auto}
.panel h3{margin:0 0 10px;font-size:13px;font-weight:600;color:#c9d1d9;letter-spacing:.02em}
label.field{display:block;font-size:12px;color:var(--muted);margin-bottom:5px}
input[type=text]{width:100%;padding:8px 10px;background:#0d1117;border:1px solid var(--line);border-radius:6px;color:var(--text)}
.check{display:flex;gap:8px;align-items:flex-start;margin:10px 0;font-size:12px;color:#c9d1d9}
.buttons{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.buttons .wide{grid-column:1/-1}
button{padding:9px 12px;border:1px solid var(--line);border-radius:7px;background:#21262d;color:var(--text);cursor:pointer;font-size:13px}
button:hover:not(:disabled){border-color:#8b949e;background:#30363d}
button:disabled{opacity:.38;cursor:not-allowed}
button.primary{border-color:#1f6feb;background:#1f6feb22}button.primary:hover:not(:disabled){background:#1f6feb44}
button.danger{border-color:#da3633;background:#da363322}
.notice{font-size:12px;color:var(--muted);margin:8px 0 0}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.metric{background:#0d1117;border:1px solid var(--line);border-radius:7px;padding:7px 9px;min-width:0}
.metric .k{font-size:11px;color:var(--muted)}
.metric .v{font-size:13px;font-weight:600;word-break:break-word;margin-top:1px}
.v.ok{color:var(--ok)}.v.warn{color:var(--warn)}.v.bad{color:var(--bad)}
#steps{margin:8px 0 0;padding-left:20px;font-size:12px;color:#c9d1d9}
#steps li{margin:3px 0}#steps li.running{color:var(--accent)}#steps li.ok{color:var(--ok)}#steps li.failed{color:var(--bad)}
details{margin-top:10px;font-size:12px;color:var(--muted)}
details pre{max-height:220px;overflow:auto;background:#0d1117;border:1px solid var(--line);border-radius:6px;padding:8px;font-size:11px}
.previews{min-height:0;display:flex;flex-direction:column;gap:10px}
.previews .bar{display:flex;align-items:center;gap:10px;flex:0 0 auto}
.previews .bar h3{margin:0;font-size:13px}
.previews .bar .spacer{flex:1}
.grid{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:10px}
.tile{position:relative;min-height:0;background:#000;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.tile .label{position:absolute;top:8px;left:8px;z-index:2;background:#000a;border:1px solid #ffffff18;border-radius:5px;padding:2px 7px;font-size:11px;color:#e6edf3}
.tile .fs{position:absolute;top:6px;right:6px;z-index:2;padding:4px 8px;font-size:11px;background:#000a}
.tile img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000}
.tile.offline::after{content:"画面不可用";position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:13px}
.tile:fullscreen{border:0;border-radius:0}
.tile:fullscreen img{object-fit:contain}
a{color:var(--accent)}
header a.hbtn{padding:9px 12px;border:1px solid var(--line);border-radius:7px;background:#21262d;color:var(--text);font-size:13px;text-decoration:none;line-height:1.2}
header a.hbtn:hover{border-color:#8b949e;background:#30363d}
@media (max-width:1100px){
  body{overflow:auto}main{grid-template-columns:1fr;min-height:auto}
  aside{overflow:visible}.previews{min-height:70vh}
}
</style></head><body>
<header>
  <h1>Xcore 数采面板</h1>
  <span id="mode" class="badge off">只读</span>
  <span id="followBadge" class="badge off">未跟随</span>
  <span class="spacer"></span>
  <a id="lelab" class="hbtn" target="_blank" rel="noopener">LeLab 数据浏览</a>
  <button id="focus" type="button">最大化预览</button>
  <button id="maximize" type="button">全屏</button>
</header>
<main>
<aside>
  <section class="panel">
    <h3>任务与会话</h3>
    <label class="field" for="task">任务描述</label>
    <input id="task" type="text" placeholder="pick and place">
    <label class="check"><input id="confirm" type="checkbox"> 我已确认 CR7 与夹爪运动范围安全</label>
    <div class="buttons">
      <button id="b-start" class="primary">启动跟随</button>
      <button id="b-stop">停止跟随</button>
      <button id="b-record">开始记录</button>
      <button id="b-save">保存</button>
      <button id="b-discard">丢弃</button>
      <button id="b-finish" class="danger wide">结束会话（按 return_mode）</button>
    </div>
    <p id="notice" class="notice"></p>
    <ol id="steps"></ol>
  </section>
  <section class="panel">
    <h3>实时状态</h3>
    <div class="metrics">
      <div class="metric"><div class="k">运动状态</div><div id="m-motion" class="v">—</div></div>
      <div class="metric"><div class="k">主臂帧龄</div><div id="m-leader" class="v">—</div></div>
      <div class="metric"><div class="k">已转发</div><div id="m-forwarded" class="v">—</div></div>
      <div class="metric"><div class="k">夹爪闭合</div><div id="m-gripper" class="v">—</div></div>
      <div class="metric"><div class="k">会话</div><div id="m-session" class="v">—</div></div>
      <div class="metric"><div class="k">活动片段</div><div id="m-episode" class="v">—</div></div>
      <div class="metric"><div class="k">已保存片段</div><div id="m-episodes" class="v">—</div></div>
      <div class="metric"><div class="k">当前行数</div><div id="m-rows" class="v">—</div></div>
      <div class="metric"><div class="k">记录状态</div><div id="m-record" class="v">—</div></div>
      <div class="metric"><div class="k">转换</div><div id="m-convert" class="v">—</div></div>
    </div>
    <p id="error" class="notice"></p>
    <details><summary>原始状态 JSON</summary><pre id="raw"></pre></details>
  </section>
</aside>
<section class="previews">
  <div class="bar"><h3>实时预览</h3><span class="spacer"></span><span class="muted" style="font-size:11px;color:var(--muted)">两台相机各自 RGB／深度；点击画面右上角可单画面全屏</span></div>
  <div class="grid">
    <div class="tile" id="t-c1r"><span class="label">cam1 RGB</span><button class="fs" type="button">全屏</button><img id="c1r" alt="cam1 RGB"></div>
    <div class="tile" id="t-c1d"><span class="label">cam1 深度</span><button class="fs" type="button">全屏</button><img id="c1d" alt="cam1 depth"></div>
    <div class="tile" id="t-c2r"><span class="label">cam2 RGB</span><button class="fs" type="button">全屏</button><img id="c2r" alt="cam2 RGB"></div>
    <div class="tile" id="t-c2d"><span class="label">cam2 深度</span><button class="fs" type="button">全屏</button><img id="c2d" alt="cam2 depth"></div>
  </div>
</section>
</main>
<script>
let S=null,busy=false;
const $=id=>document.getElementById(id);
const esc=v=>String(v==null?'':v).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function post(path,body){return fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}).then(async r=>{const j=await r.json().catch(()=>({error:r.statusText}));if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;});}
function motion(){return (S&&S.remote&&S.remote.motion)||{};}
function recording(){return (S&&S.remote&&S.remote.recording)||{};}
function armed(){const m=motion();return !!m.armed&&m.state==='following';}
function episodeActive(){const e=recording().active_episode;return e!==null&&e!==undefined;}
function jobRunning(){return !!(S&&S.job&&S.job.state==='running');}
function conversionRunning(){const c=S&&S.remote&&S.remote.conversion&&S.remote.conversion.last;return !!(c&&['queued','running'].includes(c.state));}
function setV(id,text,cls){const el=$(id);el.textContent=text==null?'—':String(text);el.className='v'+(cls?' '+cls:'');}
function setSrc(img,url,tile){
  if(!url)return;
  if(img.dataset.url!==url){img.dataset.url=url;img.src=url;}
  if(!img.dataset.bound){img.dataset.bound='1';
    img.onerror=()=>{$(tile).classList.add('offline');setTimeout(()=>{if(img.dataset.url)img.src=img.dataset.url+'?retry='+Date.now();},2000);};
    img.onload=()=>$(tile).classList.remove('offline');}
}
function updateButtons(){
  const allow=S&&S.allow_motion,a=armed(),r=recording(),ep=episodeActive(),busyNow=busy||jobRunning()||conversionRunning()||!S||!S.ok;
  $('b-start').disabled=busyNow||!allow||a||!!r.session;
  $('b-stop').disabled=busyNow||!a;
  $('b-record').disabled=busyNow||!a||ep||!r.session;
  $('b-save').disabled=busyNow||!ep;
  $('b-discard').disabled=busyNow||!ep;
  $('b-finish').disabled=busyNow||ep||(!a&&!r.session);
}
function render(){
  if(!S)return;
  const m=motion(),r=recording(),conv=(S.remote&&S.remote.conversion&&S.remote.conversion.last)||null;
  $('mode').textContent=S.allow_motion?'运动已授权':'只读';
  $('mode').className='badge '+(S.allow_motion?'on':'off');
  $('followBadge').textContent=armed()?'跟随中':(m.state||'未跟随');
  $('followBadge').className='badge '+(armed()?'on':'off');
  setV('m-motion',m.state,armed()?'ok':(m.state==='error'?'bad':''));
  const leaderAge=(S.remote&&S.remote.leader_age_s);setV('m-leader',leaderAge==null?'—':(Number(leaderAge).toFixed(2)+' s'),(leaderAge!=null&&leaderAge>3)?'bad':'ok');
  setV('m-forwarded',m.forwarded);
  const g=m.gripper||{};setV('m-gripper',g.closure==null?'—':Number(g.closure).toFixed(3),m.gripper_enabled?'':'warn');
  setV('m-session',r.session||'—');
  setV('m-episode',episodeActive()?r.active_episode:'—');
  setV('m-episodes',r.episode_index);
  setV('m-rows',r.rows);
  setV('m-record',r.state,r.state==='failed'?'bad':(r.state==='recording'?'ok':''));
  setV('m-convert',conv?conv.state:'—',conv&&conv.state==='failed'?'bad':(conv&&conv.state==='ready'?'ok':''));
  const errors=[m.error,m.abort_reason,m.cleanup_fault,r.error,S.error,conv&&conv.state==='failed'?conv.error:null].filter(Boolean);
  $('error').textContent=errors.length?('错误：'+errors.join(' | ')):'';
  $('error').className='notice'+(errors.length?' bad':'');
  $('notice').textContent=(conversionRunning()||(S.job&&S.job.action==='finish'&&jobRunning()))?'正在结束会话、转换并校验发布数据，请等待完成后再操作。':(S.job&&S.job.action==='finish'&&S.job.state==='ready'&&S.job.publication)?'数据集已保存并发布，可以开始下一次采集。':S.allow_motion?'启动/结束会话需要勾选安全确认；保存期间跟随继续。':'只读模式：未加 --enable-motion，启动跟随已禁用。';
  $('lelab').href=S.dataset_url||'#';
  const cams=S.cameras||[];const urls=cams.map(c=>c.url||'');
  setSrc($('c1r'),urls[0]&&urls[0]+'/stream/color.mjpg','t-c1r');
  setSrc($('c1d'),urls[0]&&urls[0]+'/stream/depth.mjpg','t-c1d');
  setSrc($('c2r'),urls[1]&&urls[1]+'/stream/color.mjpg','t-c2r');
  setSrc($('c2d'),urls[1]&&urls[1]+'/stream/depth.mjpg','t-c2d');
  const steps=(S.job&&S.job.steps)||[];
  $('steps').innerHTML=steps.map(s=>`<li class="${esc(s.state)}">${esc(s.name)} — ${esc(s.state)}${s.error?'：'+esc(s.error):''}</li>`).join('');
  if(S.job&&S.job.state==='failed')$('steps').insertAdjacentHTML('beforeend',`<li class="failed">${esc(S.job.error||'任务失败')}</li>`);
  $('raw').textContent=JSON.stringify(S,null,1);
  updateButtons();
}
async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'});S=await r.json();}catch(e){S={ok:false,error:String(e),remote:{},cameras:[],allow_motion:false};}render();}
async function act(name,needsConfirm){
  if(needsConfirm&&!$('confirm').checked){alert('请先勾选运动范围安全确认');return;}
  busy=true;updateButtons();
  try{let body={task:$('task').value};if(needsConfirm){const c=await post('/api/confirmation',{confirmed:true});body.token=c.token;}await post('/api/action/'+name,body);}
  catch(e){alert(e.message);}
  busy=false;await refresh();
}
$('b-start').onclick=()=>act('start',true);
$('b-stop').onclick=()=>act('stop',false);
$('b-record').onclick=()=>act('record-start',false);
$('b-save').onclick=()=>act('record-save',false);
$('b-discard').onclick=()=>act('record-discard',false);
$('b-finish').onclick=()=>act('finish',true);
$('focus').onclick=()=>{document.body.classList.toggle('focus');$('focus').textContent=document.body.classList.contains('focus')?'显示控制':'最大化预览';};
$('maximize').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen();};
document.addEventListener('fullscreenchange',()=>{$('maximize').textContent=document.fullscreenElement?'退出全屏':'全屏';});
document.querySelectorAll('.tile .fs').forEach(btn=>{btn.onclick=()=>{const tile=btn.closest('.tile');if(document.fullscreenElement)document.exitFullscreen();else tile.requestFullscreen();};});
function heartbeat(){fetch('/api/heartbeat',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});}
heartbeat();setInterval(heartbeat,2000);
function leave(){try{navigator.sendBeacon('/api/leave',new Blob(['{}'],{type:'application/json'}));}catch(e){}}
window.addEventListener('pagehide',leave);window.addEventListener('beforeunload',leave);
refresh().then(()=>{if(S&&S.task)$('task').value=S.task;});setInterval(refresh,500);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: "WebServer"

    def log_message(self, *args):
        pass

    def reply(self, code: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def html(self, body: str) -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        return True

    def do_GET(self) -> None:
        if self.path == "/":
            return self.html(PAGE)
        if self.path in ("/api/state", "/api/health"):
            try:
                return self.reply(200, self.server.control.state())
            except Exception as exc:  # noqa: BLE001
                return self.reply(503, {"error": str(exc)})
        self.reply(404, {"error": "unknown endpoint"})

    def do_POST(self) -> None:
        try:
            if not self.same_origin():
                return self.reply(403, {"error": "cross-origin control denied"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 8192:
                raise WebError("invalid payload size")
            raw = self.rfile.read(length) if length else b"{}"
            if self.headers.get_content_type() == "application/json":
                payload = json.loads(raw)
            elif self.path == "/api/leave":
                payload = {}
            else:
                raise WebError("expected application/json")
            if not isinstance(payload, dict):
                raise WebError("expected JSON object")
            if self.path == "/api/heartbeat":
                return self.reply(200, self.server.control.heartbeat())
            if self.path == "/api/leave":
                return self.reply(200, self.server.control.leave(payload))
            if self.path == "/api/confirmation":
                return self.reply(200, self.server.control.confirm(payload))
            if self.path.startswith("/api/action/"):
                action = self.path.rsplit("/", 1)[1]
                return self.reply(202, self.server.control.submit(action, payload))
            self.reply(404, {"error": "unknown endpoint"})
        except Exception as exc:  # noqa: BLE001
            self.reply(409, {"error": f"{type(exc).__name__}: {exc}"})


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, control: WebControl):
        self.control = control
        super().__init__(address, Handler)


def serve(settings: WebSettings, *, gripper_setup=None) -> None:
    control = WebControl(settings, gripper_setup=gripper_setup)
    server = WebServer((settings.host, settings.port), control)

    stop_event = threading.Event()

    def stop(*_args):
        stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(
        f"Xcore web panel: http://{settings.host}:{settings.port} "
        f"(motion {'enabled' if settings.allow_motion else 'read-only'})",
        flush=True,
    )

    def watchdog():
        while not stop_event.wait(1):
            reason = control.should_shutdown()
            if reason:
                print(f"[web] shutting down: {reason}", flush=True)
                control.shutdown()
                stop_event.set()
                server.shutdown()
                return

    threading.Thread(target=watchdog, name="web-watchdog", daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        control.shutdown()
        server.server_close()
