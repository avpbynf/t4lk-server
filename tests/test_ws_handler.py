"""Tests for the T4lk WebSocket session handler."""

import json
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect

from rest.engine import SegmentResult, TranscriptionResult


@pytest.fixture
def mock_ws():
    """Mock WebSocket with send_json and receive methods."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture
def mock_engine():
    """Mock WhisperEngine with transcribe_stream_pcm."""
    engine = MagicMock()

    async def fake_stream(audio, lang, prompt):
        yield SegmentResult(index=0, start=0.0, end=2.5, text=" Bonjour")
        yield TranscriptionResult(
            text="Bonjour", language="fr", duration=2.5,
            segments=[SegmentResult(index=0, start=0.0, end=2.5, text=" Bonjour")],
        )

    engine.transcribe_stream_pcm = fake_stream
    return engine


@pytest.fixture
def handler_settings():
    from rest.settings import Settings
    return Settings(
        DEVICE="cpu", GPU_TIMEOUT=5,
        WS_MAX_AUDIO_DURATION=600, WS_CHUNK_TIMEOUT=30,
    )


@pytest.mark.asyncio
async def test_handler_sends_connected_on_accept(mock_ws, mock_engine, handler_settings):
    from rest.v1.transcriptions.ws_handler import T4lkSessionHandler

    mock_ws.receive.side_effect = WebSocketDisconnect()

    handler = T4lkSessionHandler(mock_engine, handler_settings)
    await handler.run(mock_ws)

    mock_ws.accept.assert_called_once()
    connected_call = mock_ws.send_json.call_args_list[0]
    msg = connected_call[0][0]
    assert msg["type"] == "connected"
    assert "server_version" in msg
    assert msg["max_duration"] == 600


@pytest.mark.asyncio
async def test_handler_start_stop_lifecycle(mock_ws, mock_engine, handler_settings):
    from rest.v1.transcriptions.ws_handler import T4lkSessionHandler

    audio_chunk = np.zeros(4800, dtype=np.float32).tobytes()

    call_sequence = [
        {"type": "text", "text": json.dumps({"type": "start", "language": "fr"})},
        {"type": "bytes", "bytes": audio_chunk},
        {"type": "text", "text": json.dumps({"type": "stop"})},
    ]
    call_idx = 0

    async def mock_receive():
        nonlocal call_idx
        if call_idx >= len(call_sequence):
            raise WebSocketDisconnect()
        msg = call_sequence[call_idx]
        call_idx += 1
        return msg

    mock_ws.receive = mock_receive

    handler = T4lkSessionHandler(mock_engine, handler_settings)
    await handler.run(mock_ws)

    sent = [call[0][0] for call in mock_ws.send_json.call_args_list]
    types = [m["type"] for m in sent]
    assert "connected" in types
    assert "ready" in types
    assert "segment" in types
    assert "done" in types


@pytest.mark.asyncio
async def test_handler_empty_stop_returns_empty_done(mock_ws, mock_engine, handler_settings):
    from rest.v1.transcriptions.ws_handler import T4lkSessionHandler

    call_sequence = [
        {"type": "text", "text": json.dumps({"type": "start", "language": "fr"})},
        {"type": "text", "text": json.dumps({"type": "stop"})},
    ]
    call_idx = 0

    async def mock_receive():
        nonlocal call_idx
        if call_idx >= len(call_sequence):
            raise WebSocketDisconnect()
        msg = call_sequence[call_idx]
        call_idx += 1
        return msg

    mock_ws.receive = mock_receive

    handler = T4lkSessionHandler(mock_engine, handler_settings)
    await handler.run(mock_ws)

    sent = [call[0][0] for call in mock_ws.send_json.call_args_list]
    done_msgs = [m for m in sent if m["type"] == "done"]
    assert len(done_msgs) == 1
    assert done_msgs[0]["text"] == ""
    assert done_msgs[0]["duration"] == 0.0


@pytest.mark.asyncio
async def test_handler_cancel_clears_buffer(mock_ws, mock_engine, handler_settings):
    from rest.v1.transcriptions.ws_handler import T4lkSessionHandler

    audio_chunk = np.zeros(4800, dtype=np.float32).tobytes()
    call_sequence = [
        {"type": "text", "text": json.dumps({"type": "start"})},
        {"type": "bytes", "bytes": audio_chunk},
        {"type": "text", "text": json.dumps({"type": "cancel"})},
    ]
    call_idx = 0

    async def mock_receive():
        nonlocal call_idx
        if call_idx >= len(call_sequence):
            raise WebSocketDisconnect()
        msg = call_sequence[call_idx]
        call_idx += 1
        return msg

    mock_ws.receive = mock_receive

    handler = T4lkSessionHandler(mock_engine, handler_settings)
    await handler.run(mock_ws)

    sent = [call[0][0] for call in mock_ws.send_json.call_args_list]
    types = [m["type"] for m in sent]
    assert "cancelled" in types
    assert "segment" not in types


@pytest.mark.asyncio
async def test_handler_start_during_session_returns_error(mock_ws, mock_engine, handler_settings):
    from rest.v1.transcriptions.ws_handler import T4lkSessionHandler

    call_sequence = [
        {"type": "text", "text": json.dumps({"type": "start"})},
        {"type": "text", "text": json.dumps({"type": "start"})},
    ]
    call_idx = 0

    async def mock_receive():
        nonlocal call_idx
        if call_idx >= len(call_sequence):
            raise WebSocketDisconnect()
        msg = call_sequence[call_idx]
        call_idx += 1
        return msg

    mock_ws.receive = mock_receive

    handler = T4lkSessionHandler(mock_engine, handler_settings)
    await handler.run(mock_ws)

    sent = [call[0][0] for call in mock_ws.send_json.call_args_list]
    errors = [m for m in sent if m["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "session_active"
