import http.client
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tools.config_defaults import load
from xcore_controller import dataset_browser
from xcore_controller.dataset_browser import (
    Pulls,
    browser_entry_url,
    browser_html,
    frontend_revision,
    make_server,
)


@pytest.fixture
def browser(tmp_path):
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/edit-dataset"):
                if self.headers.get("If-Modified-Since") or self.headers.get(
                    "If-None-Match"
                ):
                    self.send_response(304)
                    self.end_headers()
                    return
                body = b"<html><head></head><body>LeLab</body></html>"
                content_type = "text/html"
            else:
                body, content_type = b"abcd", "video/mp4"
            self.send_response(206 if self.headers.get("Range") else 200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if content_type == "text/html":
                self.send_header("ETag", '"old-upstream-html"')
                self.send_header("Last-Modified", "Sat, 17 Oct 2026 15:46:21 GMT")
            if self.headers.get("Range"):
                self.send_header("Content-Range", "bytes 0-3/10")
            self.end_headers()
            self.wfile.write(body)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    pulls = Pulls(tmp_path, load())
    gateway = make_server(0, upstream.server_port, pulls)
    for server in (upstream, gateway):
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def request(method, path, body=None, headers=None, follow=True):
        for _ in range(4):
            connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port)
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            result = response.status, dict(response.getheaders()), response.read()
            connection.close()
            if follow and result[0] == 307:
                path = result[1]["Location"]
                continue
            return result
        raise AssertionError("redirect loop")

    yield pulls, gateway, request
    for server in (gateway, upstream):
        server.shutdown()
        server.server_close()


def test_proxy_injects_adapter_and_preserves_video_range(browser):
    _, _, request = browser
    status, _, html = request("GET", "/edit-dataset?dataset=demo/rev-0001")
    assert status == 200 and b"/xcore-pull.js" in html
    status, headers, body = request(
        "GET", "/dataset-video", headers={"Range": "bytes=0-3"}
    )
    assert status == 206 and headers["Content-Range"] == "bytes 0-3/10"
    assert body == b"abcd"
    status, _, body = request("GET", "/api/xcore/pulls")
    assert status == 200 and json.loads(body)["local_pull"] is True


@pytest.mark.parametrize("entry", ["/", "/edit-dataset?dataset=demo%2Frev-0001"])
def test_toolbar_is_native_html_outside_react_root(entry):
    body = b'<html><head></head><body><div id="root"></div></body></html>'
    result = browser_html(body, entry)
    assert result.index(b'id="xcore-data-toolbar"') < result.index(b'id="root"')
    assert b'id="xcore-pull-link"' in result and b'target="_blank"' in result
    assert b"Pull " in result


def test_fragment_entry_is_wrapped_and_always_has_native_toolbar():
    result = browser_html(b'<h1>Home</h1><a href="/edit-dataset">Datasets</a>', "/")
    assert b"</head>" in result and b"/xcore-pull.js" in result
    assert b'id="xcore-data-toolbar"' in result


def test_normal_entry_upgrades_once_and_preserves_selected_dataset(browser):
    _, _, request = browser
    original = "/edit-dataset?dataset=demo%2Frev-0001&episode=2&xcore_ui=old"
    status, headers, _ = request("GET", original, follow=False)
    assert status == 307
    assert headers["Location"] == browser_entry_url(original)
    assert "dataset=demo%2Frev-0001" in headers["Location"]
    assert "episode=2" in headers["Location"]
    status, _, body = request("GET", headers["Location"], follow=False)
    assert status == 200 and b'id="xcore-data-toolbar"' in body


def test_cached_html_validation_never_reuses_original_upstream_document(browser):
    _, _, request = browser
    status, headers, body = request(
        "GET",
        browser_entry_url("/edit-dataset"),
        headers={
            "If-None-Match": '"old-upstream-html"',
            "If-Modified-Since": "Sat, 17 Oct 2026 15:46:21 GMT",
        },
    )
    assert status == 200 and b'id="xcore-data-toolbar"' in body
    assert "Last-Modified" not in headers and "ETag" not in headers
    assert "no-store" in headers["Cache-Control"] and headers["Expires"] == "0"
    assert frontend_revision().encode() in body


def test_head_matches_current_html_without_cache_validators(browser):
    _, _, request = browser
    url = browser_entry_url("/edit-dataset")
    status, headers, body = request("GET", url)
    head_status, head_headers, head_body = request("HEAD", url)
    assert status == head_status == 200 and head_body == b""
    assert int(head_headers["Content-Length"]) == len(body)
    assert "ETag" not in head_headers and "Last-Modified" not in head_headers
    assert head_headers["Cache-Control"] == headers["Cache-Control"]


def test_pull_script_uses_same_content_version_as_entry(browser):
    _, _, request = browser
    status, _, body = request("GET", "/xcore-pull.js")
    assert status == 200
    assert b"__XCORE_UI_REVISION__" not in body
    assert frontend_revision().encode() in body


def test_upload_url_serves_local_pull_page_without_hub_bundle(browser):
    _, _, request = browser
    status, headers, body = request("GET", "/upload?dataset=demo/rev-0001")
    assert status == 200 and "no-store" in headers["Cache-Control"]
    assert b"xp-source" in body and b"xp-pull-content" in body
    assert b"/xcore-pull.js" in body and b'type="module"' not in body


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_proxy_recovers_read_requests_without_replaying_writes(
    browser, monkeypatch, method
):
    pulls, gateway, request = browser
    native = http.client.HTTPConnection
    failed = []
    recovered = []

    class Disconnected:
        def request(self, *args, **kwargs):
            raise ConnectionRefusedError("data unit was stopped")

        def close(self):
            pass

    def connect(host, port, **kwargs):
        if port != gateway.server_port and not failed:
            failed.append(port)
            return Disconnected()
        return native(host, port, **kwargs)

    monkeypatch.setattr(dataset_browser.http.client, "HTTPConnection", connect)
    monkeypatch.setattr(pulls, "ensure_upstream", lambda port: recovered.append(port))
    if method == "GET":
        assert request("GET", "/edit-dataset")[0] == 200
        assert recovered == failed
    else:
        origin = f"http://127.0.0.1:{gateway.server_port}"
        assert request("POST", "/dataset-info", "{}", {"Origin": origin})[0] == 502
        assert recovered == []


def test_upstream_recovery_starts_only_dataset_unit(tmp_path, monkeypatch):
    pulls = Pulls(tmp_path, load())
    alive, calls = [], []

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args):
            if not alive:
                raise ConnectionRefusedError()

        def getresponse(self):
            return type("Response", (), {"status": 200})()

        def close(self):
            pass

    def start(command, **kwargs):
        calls.append(command)
        assert command[-1] == "systemctl --user start xcore-dataset.service"
        alive.append(True)

    monkeypatch.setattr(dataset_browser.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(dataset_browser.subprocess, "run", start)
    pulls.ensure_upstream(8091)
    pulls.ensure_upstream(8091)
    assert len(calls) == 1


def test_pull_requires_same_origin_token_and_never_forwards_upload(
    browser, monkeypatch
):
    pulls, gateway, request = browser
    calls = []
    monkeypatch.setattr(
        pulls, "start", lambda *args: calls.append(args) or {"id": "job"}
    )
    body = json.dumps({"dataset": "demo/rev-0001", "representation": "joints"})
    headers = {"Content-Type": "application/json", "X-Xcore-Token": pulls.token}
    assert request("POST", "/api/xcore/pulls", body, headers)[0] == 403
    headers["Origin"] = f"http://127.0.0.1:{gateway.server_port}"
    assert (
        request("POST", "/api/xcore/pulls", body, {**headers, "X-Xcore-Token": "bad"})[
            0
        ]
        == 403
    )
    assert request("POST", "/api/xcore/pulls", body, headers)[0] == 202
    assert calls == [("demo/rev-0001", "joints")]
    assert request("POST", "/upload-dataset", body, headers)[0] == 403
    assert (
        request("GET", "/xcore-pull.js", headers={"Sec-Fetch-Site": "cross-site"})[0]
        == 403
    )
    assert (
        request("GET", "/api/xcore/pulls", headers={"Host": "evil.example"})[0] == 403
    )


@pytest.mark.parametrize(
    "dataset,representation",
    [
        ("../raw/rev-0001", "pose10"),
        ("demo/rev-0001/..", "pose10"),
        ("demo/rev-0001", "other"),
        (None, "pose10"),
        ("demo;command/rev-0001", "joints"),
    ],
)
def test_invalid_pull_is_rejected_without_network(tmp_path, dataset, representation):
    with pytest.raises(ValueError):
        Pulls(tmp_path, load()).start(dataset, representation)


def test_jobs_prepare_requested_format_then_reuse_cli_pull(tmp_path, monkeypatch):
    pulls = Pulls(tmp_path, load())
    final = tmp_path / "data/joints-export/rev-0001"
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[0] == "ssh":
            assert "--representation joints" in args[-1]
            assert "xcore-runtime/media" in args[-1]
            result = {"result": {"dataset_id": "joints-export", "revision": "rev-0001"}}
        else:
            assert args[-3:] == ["--joints", "joints-export", "rev-0001"]
            result = {"path": str(final)}
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"ok": True, **result}), ""
        )

    monkeypatch.setattr(subprocess, "run", run)
    pulls.job = {"state": "running"}
    pulls._run({"dataset": "source/rev-0001", "representation": "joints"})
    assert len(calls) == 2
    assert pulls.status()["job"]["state"] == "ready"
    assert Path(pulls.status()["job"]["path"]) == final


def test_remote_failure_never_reports_a_local_path(tmp_path, monkeypatch):
    pulls = Pulls(tmp_path, load())
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 1, "", "missing joints_rad"
        ),
    )
    pulls.job = {"state": "running", "path": None}
    pulls._run({"dataset": "source/rev-0001", "representation": "joints"})
    job = pulls.status()["job"]
    assert job["state"] == "failed" and job["path"] is None
    assert "missing joints_rad" in job["error"]
