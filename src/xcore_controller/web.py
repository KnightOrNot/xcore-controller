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
            "dataset_url": self.settings.dataset_url,
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
                    step("session/stop", lambda: self.remote.call("session/stop"))
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

    # ---------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        """Stop following on process exit; never save, discard, or return."""
        try:
            state = self.remote.state()
        except Exception:
            return
        motion = state.get("motion") or {}
        if motion.get("armed"):
            try:
                self.remote.call("stop")
                self.log("[web] following stopped; no automatic return was sent")
            except Exception as exc:  # noqa: BLE001
                self.log(f"[web] stop on shutdown failed: {exc}")
        if (state.get("recording") or {}).get("active_episode") is not None:
            self.log("[web] active episode left uncommitted; use CLI/dataset tools")


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Xcore 数采面板</title>
<style>
:root{color-scheme:dark}body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#111;color:#ddd}
header{padding:12px 18px;background:#1b1b1b;border-bottom:1px solid #333}
main{display:grid;grid-template-columns:360px 1fr;gap:16px;padding:16px}
section{background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:14px}
button{padding:8px 12px;margin:3px;border:1px solid #555;border-radius:6px;background:#2a2a2a;color:#eee}
button:disabled{opacity:.4}button.danger{border-color:#a33}
input[type=text]{width:100%;padding:7px;background:#111;border:1px solid #444;color:#eee;border-radius:5px}
pre{white-space:pre-wrap;word-break:break-word;font-size:12px;color:#bbb}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
img{width:100%;background:#000;border-radius:5px}
.ok{color:#6c6}.bad{color:#e77}.muted{color:#888}
</style></head><body>
<header><b>Xcore 数采面板</b> <span class="muted">本地 loopback；关闭页面不会停止硬件</span></header>
<main>
<section>
<h3>任务</h3>
<input id="task" type="text" placeholder="pick and place">
<label><input id="confirm" type="checkbox"> 我已确认 CR7 与夹爪运动范围安全</label>
<div>
<button id="b-start">启动跟随</button>
<button id="b-stop">停止跟随</button>
</div><div>
<button id="b-record">开始记录</button>
<button id="b-save">保存</button>
<button id="b-discard">丢弃</button>
</div><div>
<button id="b-finish" class="danger">结束会话（按 return_mode）</button>
</div>
<p id="notice" class="muted"></p>
<h3>状态</h3>
<pre id="state">加载中…</pre>
</section>
<section>
<h3>实时预览</h3>
<div class="grid">
<div><div class="muted">cam1 RGB</div><img id="c1r"></div>
<div><div class="muted">cam1 Depth</div><img id="c1d"></div>
<div><div class="muted">cam2 RGB</div><img id="c2r"></div>
<div><div class="muted">cam2 Depth</div><img id="c2d"></div>
</div>
<p><a id="lelab" target="_blank" rel="noopener">打开 LeLab 数据浏览</a></p>
</section>
</main>
<script>
let S=null, busy=false;
const $=id=>document.getElementById(id);
function post(path,body){return fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}).then(async r=>{const j=await r.json().catch(()=>({error:r.statusText}));if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;});}
function armed(){const m=S&&S.remote&&S.remote.motion||{};return !!m.armed&&m.state==='following';}
function recording(){return (S&&S.remote&&S.remote.recording)||{};}
function jobRunning(){return S&&S.job&&S.job.state==='running';}
function updateButtons(){
  const allow=S&&S.allow_motion, a=armed(), r=recording(), ep=r.active_episode!==null&&r.active_episode!==undefined;
  $('b-start').disabled=busy||jobRunning()||!allow||a||!!r.session;
  $('b-stop').disabled=busy||jobRunning()||!a;
  $('b-record').disabled=busy||jobRunning()||!a||ep||!r.session;
  $('b-save').disabled=busy||jobRunning()||!ep;
  $('b-discard').disabled=busy||jobRunning()||!ep;
  $('b-finish').disabled=busy||jobRunning()||ep||(!a&&!r.session);
}
function showState(){
  if(!S){return;}
  const m=S.remote&&S.remote.motion||{}, r=recording();
  $('state').textContent=JSON.stringify({
    remote_ok:S.ok,remote_error:S.error,
    motion:m.state,armed:m.armed,leader_age_s:S.remote&&S.remote.leader_age_s,
    gripper:m.gripper,forwarded:m.forwarded,error:m.error,abort:m.abort_reason,
    session:r.session,episode:r.active_episode,episode_index:r.episode_index,
    rows:r.rows,record_state:r.state,record_error:r.error,
    conversion:S.remote&&S.remote.conversion,
    cameras:(S.cameras||[]).map(c=>({name:c.name,state:c.state,age:c.frame_age_s,recording:c.recording,error:c.error})),
    job:S.job
  },null,1);
  const c1=S.cameras&&S.cameras[0]||{},c2=S.cameras&&S.cameras[1]||{};
  $('c1r').src=(c1.url||'')+'/stream/color.mjpg';$('c1d').src=(c1.url||'')+'/stream/depth.mjpg';
  $('c2r').src=(c2.url||'')+'/stream/color.mjpg';$('c2d').src=(c2.url||'')+'/stream/depth.mjpg';
  $('lelab').href=S.dataset_url||'#';
  if(!$('task').value&&S.task)$('task').value=S.task;
  $('notice').textContent=S.allow_motion?'运动已授权：启动/结束需要勾选安全确认。':'只读模式：启动跟随已禁用（未加 --enable-motion）。';
  updateButtons();
}
async function refresh(){try{const r=await fetch('/api/state');S=await r.json();}catch(e){S={ok:false,error:String(e),remote:{},cameras:[]};}showState();}
async function act(name,needsConfirm){
  if(needsConfirm&&!$('confirm').checked){alert('请先勾选运动范围安全确认');return;}
  busy=true;updateButtons();
  try{
    let body={task:$('task').value};
    if(needsConfirm){const c=await post('/api/confirmation',{confirmed:true});body.token=c.token;}
    await post('/api/action/'+name,body);
  }catch(e){alert(e.message);}
  busy=false;await refresh();
}
$('b-start').onclick=()=>act('start',true);
$('b-stop').onclick=()=>act('stop',false);
$('b-record').onclick=()=>act('record-start',false);
$('b-save').onclick=()=>act('record-save',false);
$('b-discard').onclick=()=>act('record-discard',false);
$('b-finish').onclick=()=>act('finish',true);
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
            if self.headers.get_content_type() != "application/json":
                raise WebError("expected application/json")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise WebError("invalid payload size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise WebError("expected JSON object")
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

    def stop(*_args):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(
        f"Xcore web panel: http://{settings.host}:{settings.port} "
        f"(motion {'enabled' if settings.allow_motion else 'read-only'})",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        control.shutdown()
        server.server_close()
