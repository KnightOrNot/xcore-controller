"""Loopback LeLab proxy with explicit representation-aware local pull jobs."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}

FRONTEND_ROUTES = (
    "/edit-dataset",
    "/upload",
    "/teleoperation",
    "/recording",
    "/training",
    "/inference",
    "/calibration",
)


def frontend_revision():
    digest = hashlib.sha256()
    for name in (
        "dataset_browser.py",
        "lelab_pull.js",
        "lelab_toolbar.html",
        "lelab_upload.html",
    ):
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()[:12]


def browser_entry_url(url):
    parsed = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k != "xcore_ui"
    ]
    query.append(("xcore_ui", frontend_revision()))
    return urlunsplit(parsed._replace(query=urlencode(query)))


def frontend_entry(path):
    path = urlsplit(path).path
    return path == "/" or any(
        path == route or path.startswith(route + "/") for route in FRONTEND_ROUTES
    )


def last_json(output):
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("ok") is True:
            return value
    raise RuntimeError("data command did not return a successful result")


def browser_html(body, request_path):
    """Render a native toolbar outside the upstream React-owned root.

    Every entry document carries it, so SPA home -> datasets navigation cannot
    discard the Pull entry, and it remains usable even if adapter JS fails.
    """
    dataset = parse_qs(urlsplit(request_path).query).get("dataset", [""])[0]
    destination = "/upload"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/rev-[0-9]{4,}", dataset):
        destination += "?" + urlencode({"dataset": dataset})
    toolbar = (
        Path(__file__)
        .with_name("lelab_toolbar.html")
        .read_text()
        .replace("__PULL_URL__", escape(browser_entry_url(destination), quote=True))
        .encode()
    )
    if b"</head>" not in body:
        body = b"<!doctype html><html><head></head><body>" + body + b"</body></html>"
    adapter = f'<script src="/xcore-pull.js?v={frontend_revision()}"></script>'
    body = body.replace(b"</head>", adapter.encode() + b"</head>", 1)
    return re.sub(rb"(<body\b[^>]*>)", lambda m: m[1] + toolbar, body, count=1)


class Pulls:
    def __init__(self, root, config):
        self.root, self.config = Path(root), config
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.job = None
        self._upstream_lock = threading.Lock()
        self._upstream_start = 0.0

    def ensure_upstream(self, port):
        """Revive only the data unit when collection cleanup stopped it."""

        def healthy():
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            try:
                connection.request("GET", "/api/datasets")
                return connection.getresponse().status == 200
            except (OSError, http.client.HTTPException):
                return False
            finally:
                connection.close()

        with self._upstream_lock:
            if healthy():
                return
            if time.monotonic() - self._upstream_start < 5:
                raise RuntimeError("远端数据服务尚未恢复，请稍后重试")
            self._upstream_start = time.monotonic()
            target = self.config.get("remote.camera_ssh_target")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+", target):
                raise ValueError("invalid dataset SSH target")
            timeout = self.config.get("timeouts.startup_ready_s")
            subprocess.run(
                [
                    "ssh",
                    "-T",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"ConnectTimeout={self.config.get('timeouts.ssh_connect_s')}",
                    target,
                    "systemctl --user start xcore-dataset.service",
                ],
                check=True,
                timeout=timeout,
                capture_output=True,
            )
            deadline = time.monotonic() + timeout
            while not healthy():
                if time.monotonic() >= deadline:
                    raise RuntimeError("等待远端数据服务恢复超时")
                time.sleep(0.2)

    def status(self):
        with self.lock:
            return {"local_pull": True, "job": dict(self.job) if self.job else None}

    def start(self, dataset, representation):
        if not isinstance(dataset, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/rev-[0-9]{4,}", dataset
        ):
            raise ValueError("请选择已发布的数据集版本（dataset/rev-NNNN）")
        if representation not in ("pose10", "joints"):
            raise ValueError("请选择 --pose 或 --joints")
        with self.lock:
            if self.job and self.job["state"] == "running":
                if (self.job["dataset"], self.job["representation"]) != (
                    dataset,
                    representation,
                ):
                    raise ValueError("已有拉取任务正在进行，请等待完成")
                return dict(self.job)
            self.job = {
                "id": secrets.token_hex(12),
                "state": "running",
                "dataset": dataset,
                "representation": representation,
                "phase": "正在检查远端格式；需要时从原始数据生成所选格式…",
                "path": None,
                "error": None,
            }
            job = dict(self.job)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _update(self, **fields):
        with self.lock:
            self.job.update(fields)

    def _run(self, job):
        try:
            from .launcher import home_path

            roles = self.config.data["roles"]
            dataset, revision = job["dataset"].split("/")
            target = self.config.get("remote.camera_ssh_target")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+", target):
                raise ValueError("invalid SSH target")
            python = home_path(roles["remote_dataset_python"])
            data_root = home_path(roles["remote_data_root"])
            runtime = str(Path(roles["remote_dataset_python"]).parents[2])
            media = home_path(runtime + "/media")
            torch = home_path(
                runtime + "/dataset-venv/lib/python3.12/site-packages/torch/lib"
            )
            # User-selected fields are validated and individually shell-quoted.
            command = (
                'cd "$HOME"/project/xcore-dataset && '
                "unset PYTHONPATH PYTHONHOME && "
                f"export PATH={media}/bin:/usr/bin:/bin && "
                f"export LD_LIBRARY_PATH={media}/lib:{torch} && "
                f"{python} -m xcore_dataset.cli export "
                f"{shlex.quote(dataset)} {shlex.quote(revision)} "
                f"--root {data_root} --representation {job['representation']}"
            )
            remote = subprocess.run(
                [
                    "ssh",
                    "-T",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"ConnectTimeout={self.config.get('timeouts.ssh_connect_s')}",
                    target,
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=3600,
            )
            if remote.returncode:
                raise RuntimeError(remote.stderr[-4000:] or "远端格式准备失败")
            exported = last_json(remote.stdout)["result"]
            self._update(phase="正在拉取到本地并校验 SHA-256、回读数据…")
            pulled = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "xcore_controller.launcher",
                    "pull",
                    "--joints" if job["representation"] == "joints" else "--pose",
                    exported["dataset_id"],
                    exported["revision"],
                ],
                cwd=self.root,
                env=dict(os.environ),
                capture_output=True,
                text=True,
                timeout=3600,
            )
            if pulled.returncode:
                raise RuntimeError(pulled.stderr[-4000:] or "拉取或本地校验失败")
            result = last_json(pulled.stdout)
            path = str(Path(result.get("path") or result["already_present"]).resolve())
            self._update(state="ready", phase="拉取及校验完成", path=path)
        except Exception as exc:  # noqa: BLE001 - shown in the local pull dialog
            self._update(state="failed", phase="拉取失败", error=str(exc))


def make_server(port, upstream_port, pulls):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, dict):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if content_type.startswith("text/html"):
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def trusted(self):
            host = self.headers.get("Host", "")
            if host not in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            ):
                self.send(403, {"error": "invalid local Host"})
                return False
            if self.command == "POST" and (
                self.headers.get("Origin") != "http://" + host
            ):
                self.send(403, {"error": "same-origin requests required"})
                return False
            return True

        def do_GET(self):
            if not self.trusted():
                return
            path = urlsplit(self.path).path
            if frontend_entry(self.path) and parse_qs(urlsplit(self.path).query).get(
                "xcore_ui"
            ) != [frontend_revision()]:
                self.send_response(307)
                self.send_header("Location", browser_entry_url(self.path))
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                return
            if path == "/api/xcore/pulls":
                self.send(200, pulls.status())
            elif path == "/api/xcore/ui":
                self.send(200, {"revision": frontend_revision()})
            elif path in ("/upload", "/upload/"):
                self.send(
                    200,
                    Path(__file__)
                    .with_name("lelab_upload.html")
                    .read_bytes()
                    .replace(
                        b"/xcore-pull.js?v=2",
                        f"/xcore-pull.js?v={frontend_revision()}".encode(),
                    ),
                    "text/html; charset=utf-8",
                )
            elif path == "/xcore-pull.js":
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    self.send(403, {"error": "same-origin script required"})
                    return
                script = Path(__file__).with_name("lelab_pull.js").read_text()
                self.send(
                    200,
                    script.replace("__XCORE_TOKEN__", pulls.token)
                    .replace("__XCORE_UI_REVISION__", frontend_revision())
                    .encode(),
                    "text/javascript; charset=utf-8",
                )
            else:
                self.proxy()

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            if not self.trusted():
                return
            path = urlsplit(self.path).path
            if path != "/api/xcore/pulls":
                if path in ("/dataset-info", "/delete-dataset"):
                    self.proxy()
                else:
                    self.send(403, {"error": "此页面仅支持浏览和拉取到本地"})
                return
            if not secrets.compare_digest(
                self.headers.get("X-Xcore-Token", ""), pulls.token
            ):
                self.send(403, {"error": "invalid pull token"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("invalid request size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("invalid request")
                job = pulls.start(body.get("dataset"), body.get("representation"))
            except (ValueError, TypeError) as exc:
                self.send(400, {"error": str(exc)})
                return
            self.send(202, {"job": job})

        def proxy(self, retry=True):
            connection = http.client.HTTPConnection(
                "127.0.0.1", upstream_port, timeout=30
            )
            response_started = False
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 1024 * 1024:
                    self.send(413, {"error": "request too large"})
                    return
                headers = {
                    k: v
                    for k, v in self.headers.items()
                    if k.lower() not in HOP_HEADERS
                }
                document = frontend_entry(self.path) or "text/html" in self.headers.get(
                    "Accept", ""
                )
                if document:
                    headers = {
                        k: v
                        for k, v in headers.items()
                        if k.lower()
                        not in ("if-none-match", "if-modified-since", "if-range")
                    }
                headers["Accept-Encoding"] = "identity"
                connection.request(
                    "GET" if self.command == "HEAD" and document else self.command,
                    self.path,
                    body=self.rfile.read(length) if length else None,
                    headers=headers,
                )
                response = connection.getresponse()
                html = (
                    response.status == 200
                    and (self.command == "GET" or (self.command == "HEAD" and document))
                    and "text/html" in response.getheader("Content-Type", "")
                )
                body = None
                if html:
                    body = browser_html(response.read(), self.path)
                self.send_response(response.status)
                response_started = True
                for key, value in response.getheaders():
                    if key.lower() not in HOP_HEADERS and not (
                        (html or document)
                        and key.lower()
                        in (
                            "etag",
                            "last-modified",
                            "cache-control",
                            "expires",
                            "pragma",
                        )
                    ):
                        self.send_header(key, value)
                if html or document:
                    self.send_header(
                        "Cache-Control", "no-store, no-cache, must-revalidate"
                    )
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Expires", "0")
                if body is not None:
                    self.send_header("Content-Length", str(len(body)))
                elif response.getheader("Content-Length") is not None:
                    self.send_header(
                        "Content-Length", response.getheader("Content-Length")
                    )
                else:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                if self.command != "HEAD":
                    if body is not None:
                        self.wfile.write(body)
                    else:
                        while block := response.read(64 * 1024):
                            self.wfile.write(block)
            except (OSError, ValueError, http.client.HTTPException) as exc:
                error_message = str(exc)
                if retry and not response_started and self.command in ("GET", "HEAD"):
                    try:
                        pulls.ensure_upstream(upstream_port)
                        return self.proxy(retry=False)
                    except Exception as recovery_error:  # noqa: BLE001
                        error_message = str(recovery_error)
                self.close_connection = True
                if not response_started and not self.wfile.closed:
                    try:
                        self.send(
                            502, {"error": f"远端数据服务连接失败：{error_message}"}
                        )
                    except OSError:
                        pass
            finally:
                connection.close()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(root, config, ssh, target):
    port = config.get("roles.dataset_port")
    upstream = config.get("roles.dataset_tunnel_port")
    server = make_server(port, upstream, Pulls(root, config))
    tunnel = subprocess.Popen(
        ssh + ["-N", "-L", f"127.0.0.1:{upstream}:127.0.0.1:{port}", target]
    )
    try:
        # Establish SSH before advertising a ready local browser.
        for _ in range(100):
            if tunnel.poll() is not None:
                raise RuntimeError("dataset SSH tunnel exited before becoming ready")
            probe = http.client.HTTPConnection("127.0.0.1", upstream, timeout=0.2)
            try:
                probe.request("GET", "/api/datasets")
                if probe.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(0.1)
            finally:
                probe.close()
        else:
            raise RuntimeError("dataset SSH tunnel did not become ready")
        print(
            f"LeLab: {browser_entry_url(f'http://127.0.0.1:{port}/edit-dataset')} "
            "（点击 Pull 到本地，可选择 --pose / --joints）",
            flush=True,
        )
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            tunnel.wait()
