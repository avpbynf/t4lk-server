"""T4lk WebSocket session handler — manages one connection's lifecycle."""

import asyncio
import enum
import json
import logging

import numpy as np
from starlette.websockets import WebSocket, WebSocketDisconnect

from rest.engine import SegmentResult, WhisperEngine
from rest.exceptions import QueueTimeoutError
from rest.settings import SERVER_VERSION, Settings
from rest.v1.transcriptions.ws_models import (
    WsCancelledMessage,
    WsConnectedMessage,
    WsDoneMessage,
    WsErrorMessage,
    WsReadyMessage,
    WsSegmentMessage,
)

logger = logging.getLogger(__name__)


class _SessionState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class T4lkSessionHandler:
    """Manages one WebSocket connection with a single-session state machine.

    State: IDLE -> RECORDING -> TRANSCRIBING -> IDLE.
    One session at a time per connection; start is rejected if not IDLE.
    Buffer uses a mutable list for performance (append-only, cleared on reset).

    Args:
        engine: WhisperEngine instance for transcription.
        settings: Application settings.
    """

    def __init__(self, engine: WhisperEngine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings
        self._state = _SessionState.IDLE
        self._buffer: list[np.ndarray] = []
        self._language: str | None = None
        self._prompt: str | None = None

    async def run(self, ws: WebSocket) -> None:
        """Main loop: accept connection, dispatch messages until disconnect."""
        await ws.accept()
        await ws.send_json(
            WsConnectedMessage(
                server_version=SERVER_VERSION,
                max_duration=self._settings.WS_MAX_AUDIO_DURATION,
            ).model_dump()
        )

        try:
            while True:
                timeout = (
                    self._settings.WS_CHUNK_TIMEOUT
                    if self._state == _SessionState.RECORDING
                    else None
                )
                try:
                    if timeout:
                        message = await asyncio.wait_for(ws.receive(), timeout=timeout)
                    else:
                        message = await ws.receive()
                except asyncio.TimeoutError:
                    await ws.send_json(
                        WsErrorMessage(
                            code="chunk_timeout",
                            message=(
                                f"No data received for "
                                f"{self._settings.WS_CHUNK_TIMEOUT}s"
                            ),
                        ).model_dump()
                    )
                    self._buffer = []
                    self._state = _SessionState.IDLE
                    continue

                if message.get("type") == "websocket.disconnect":
                    break

                if "text" in message:
                    await self._handle_text(ws, message["text"])
                elif "bytes" in message:
                    result = self._handle_bytes(message["bytes"])
                    if result == "max_duration":
                        await ws.send_json(
                            WsErrorMessage(
                                code="max_duration",
                                message=(
                                    f"Max recording duration "
                                    f"({self._settings.WS_MAX_AUDIO_DURATION}s) "
                                    f"exceeded"
                                ),
                            ).model_dump()
                        )
                        self._buffer = []
                        self._state = _SessionState.IDLE

        except WebSocketDisconnect:
            pass
        finally:
            self._buffer = []
            logger.debug("WebSocket disconnected, buffer cleared")

    async def _handle_text(self, ws: WebSocket, raw: str) -> None:
        """Dispatch a JSON text message."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_json(
                WsErrorMessage(
                    code="invalid_json", message="Failed to parse JSON"
                ).model_dump()
            )
            return

        msg_type = data.get("type", "")

        if msg_type == "start":
            await self._handle_start(ws, data)
        elif msg_type == "stop":
            await self._handle_stop(ws)
        elif msg_type == "cancel":
            await self._handle_cancel(ws)
        else:
            await ws.send_json(
                WsErrorMessage(
                    code="unknown_message",
                    message=f"Unknown message type: {msg_type}",
                ).model_dump()
            )

    async def _handle_start(self, ws: WebSocket, data: dict) -> None:
        """Handle start message: begin a new recording session."""
        if self._state != _SessionState.IDLE:
            await ws.send_json(
                WsErrorMessage(
                    code="session_active",
                    message="A session is already in progress",
                ).model_dump()
            )
            return

        self._buffer = []
        self._language = data.get("language")
        self._prompt = data.get("prompt")
        self._state = _SessionState.RECORDING
        await ws.send_json(WsReadyMessage().model_dump())

    async def _handle_stop(self, ws: WebSocket) -> None:
        """Handle stop message: run inference and stream results."""
        if not self._buffer:
            await ws.send_json(
                WsDoneMessage(
                    text="",
                    language=self._language or "",
                    duration=0.0,
                ).model_dump()
            )
            self._state = _SessionState.IDLE
            return

        self._state = _SessionState.TRANSCRIBING
        audio = np.concatenate(self._buffer)
        self._buffer = []

        try:
            async for item in self._engine.transcribe_stream_pcm(
                audio, self._language, self._prompt
            ):
                if isinstance(item, SegmentResult):
                    await ws.send_json(
                        WsSegmentMessage(
                            index=item.index,
                            start=item.start,
                            end=item.end,
                            text=item.text,
                        ).model_dump()
                    )
                else:
                    await ws.send_json(
                        WsDoneMessage(
                            text=item.text,
                            language=item.language,
                            duration=item.duration,
                        ).model_dump()
                    )
        except QueueTimeoutError as exc:
            await ws.send_json(
                WsErrorMessage(code="queue_timeout", message=str(exc)).model_dump()
            )
        except Exception as exc:
            logger.exception("Transcription error during WebSocket session")
            await ws.send_json(
                WsErrorMessage(code="inference_error", message=str(exc)).model_dump()
            )
        finally:
            self._state = _SessionState.IDLE

    async def _handle_cancel(self, ws: WebSocket) -> None:
        """Handle cancel message: clear buffer, return to IDLE."""
        self._buffer = []
        self._state = _SessionState.IDLE
        await ws.send_json(WsCancelledMessage().model_dump())

    def _handle_bytes(self, data: bytes) -> str | None:
        """Handle binary message: append PCM chunk to buffer.

        Returns "max_duration" if the buffer exceeds the configured limit.
        """
        if self._state != _SessionState.RECORDING:
            return None
        chunk = np.frombuffer(data, dtype=np.float32)
        self._buffer.append(chunk)
        total_samples = sum(len(c) for c in self._buffer)
        if total_samples / 16000 > self._settings.WS_MAX_AUDIO_DURATION:
            return "max_duration"
        return None
