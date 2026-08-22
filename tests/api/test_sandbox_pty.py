from __future__ import annotations

import json

from fastapi.testclient import TestClient

from main import app


def test_sandbox_websocket_pty():
    client = TestClient(app)
    with client.websocket_connect("/api/v1/sandbox/terminal/ws") as websocket:
        websocket.send_text(json.dumps({"type": "input", "data": "echo test"}))
        data = websocket.receive_text()
        parsed = json.loads(data)
        assert parsed["type"] == "output"
        assert parsed["data"] == "echo test"
