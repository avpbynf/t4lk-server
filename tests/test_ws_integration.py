"""Integration tests for the T4lk WebSocket endpoint."""

import json
from unittest.mock import patch

import numpy as np
import pytest
from starlette.testclient import TestClient


@pytest.fixture
def ws_app(engine):
    """FastAPI app with mock engine for WebSocket testing."""
    with patch("rest.engine.WhisperModel"):
        from rest.main import create_app

        app = create_app()
        app.state.engine = engine
        return app


@pytest.fixture
def ws_client(ws_app):
    """Starlette TestClient for sync WebSocket testing."""
    return TestClient(ws_app)


def test_ws_connect_sends_connected(ws_client):
    """Connection is accepted and connected message is sent."""
    with ws_client.websocket_connect("/v1/t4lk/ws") as ws:
        data = ws.receive_json()
        assert data["type"] == "connected"
        assert "server_version" in data
        assert "max_duration" in data


def test_ws_full_lifecycle(ws_client):
    """Full start -> audio -> stop -> segments -> done lifecycle."""
    with ws_client.websocket_connect("/v1/t4lk/ws") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "connected"

        ws.send_json({"type": "start", "language": "fr"})
        ready = ws.receive_json()
        assert ready["type"] == "ready"

        audio = np.zeros(4800, dtype=np.float32)
        ws.send_bytes(audio.tobytes())

        ws.send_json({"type": "stop"})

        messages = []
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] == "done":
                break

        types = [m["type"] for m in messages]
        assert "segment" in types
        assert "done" in types

        done = next(m for m in messages if m["type"] == "done")
        assert "text" in done
        assert "language" in done
        assert "duration" in done


def test_ws_empty_stop(ws_client):
    """Stop with no audio returns empty done."""
    with ws_client.websocket_connect("/v1/t4lk/ws") as ws:
        ws.receive_json()  # connected
        ws.send_json({"type": "start"})
        ws.receive_json()  # ready
        ws.send_json({"type": "stop"})
        done = ws.receive_json()
        assert done["type"] == "done"
        assert done["text"] == ""


def test_ws_cancel(ws_client):
    """Cancel clears buffer and returns cancelled."""
    with ws_client.websocket_connect("/v1/t4lk/ws") as ws:
        ws.receive_json()  # connected
        ws.send_json({"type": "start"})
        ws.receive_json()  # ready

        audio = np.zeros(4800, dtype=np.float32)
        ws.send_bytes(audio.tobytes())

        ws.send_json({"type": "cancel"})
        cancelled = ws.receive_json()
        assert cancelled["type"] == "cancelled"


def test_ws_start_during_session(ws_client):
    """Start while recording returns session_active error."""
    with ws_client.websocket_connect("/v1/t4lk/ws") as ws:
        ws.receive_json()  # connected
        ws.send_json({"type": "start"})
        ws.receive_json()  # ready
        ws.send_json({"type": "start"})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "session_active"
