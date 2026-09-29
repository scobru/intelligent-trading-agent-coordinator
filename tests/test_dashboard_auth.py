"""
I comandi della Master Dashboard (cicli, pause, svincolo fondi, emergency)
vengono inoltrati ai bot con AGENT_RUN_TOKEN: senza token valido devono
essere rifiutati, qualunque header "da browser" arrivi con la richiesta.
"""

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import dashboard  # noqa: E402

COMMANDS = ["/api/run", "/api/agent_run/perp", "/api/agent_pause/perp", "/api/agent_resume/perp",
            "/api/agent_release_funds/perp", "/api/emergency_stop", "/api/emergency_resume"]


class _Coord:
    """Coordinator finto: registra i comandi che gli arrivano."""

    def __init__(self):
        self.calls = []
        self.agent_client = self

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            return {"status": "success"}
        return call


def _serve(token):
    config.DASHBOARD_RUN_TOKEN = token
    coord = _Coord()
    dashboard.MasterDashboardHandler.coordinator = coord
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.MasterDashboardHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, coord


def _post(server, path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}",
                                 data=b"{}", method="POST",
                                 headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def test_commands_rejected_without_token():
    server, coord = _serve("segreto-lungo")
    try:
        for path in COMMANDS:
            for headers in ({}, {"X-Requested-With": "DashboardUI"}, {"Sec-Fetch-Site": "same-origin"},
                            {"X-Run-Token": "sbagliato"}):
                status, _ = _post(server, path, headers)
                assert status == 403, (path, headers, status)
        assert coord.calls == []
    finally:
        server.shutdown()


def test_commands_disabled_when_token_not_configured():
    server, coord = _serve("")
    try:
        status, _ = _post(server, "/api/emergency_resume", {"X-Run-Token": ""})
        assert status == 403
        assert coord.calls == []
    finally:
        server.shutdown()


def test_valid_token_reaches_the_coordinator():
    server, coord = _serve("segreto-lungo")
    try:
        status, _ = _post(server, "/api/agent_pause/perp", {"X-Run-Token": "segreto-lungo"})
        assert status == 200
        status, _ = _post(server, "/api/agent_release_funds/perp", {"Authorization": "Bearer segreto-lungo"})
        assert status == 200
        assert coord.calls == ["pause_agent", "release_agent_funds"]
    finally:
        server.shutdown()
