"""WebSocket router for the T4lk real-time transcription protocol."""

import logging

from fastapi import APIRouter, WebSocket

from rest.engine import WhisperEngine
from rest.settings import get_settings
from rest.v1.transcriptions.ws_handler import T4lkSessionHandler

logger = logging.getLogger(__name__)

ws_router = APIRouter()

_active_connections: int = 0


@ws_router.websocket("/v1/t4lk/ws")
async def t4lk_websocket(websocket: WebSocket) -> None:
    """T4lk WebSocket endpoint for real-time audio streaming transcription.

    Enforces WS_MAX_CONNECTIONS limit. Rejects with 1013 (Try Again Later)
    if the limit is reached.

    Args:
        websocket: The incoming WebSocket connection.
    """
    global _active_connections
    settings = get_settings()

    if _active_connections >= settings.WS_MAX_CONNECTIONS:
        await websocket.close(code=1013, reason="Too many connections")
        return

    _active_connections += 1
    try:
        engine: WhisperEngine = websocket.app.state.engine
        handler = T4lkSessionHandler(engine, settings)
        await handler.run(websocket)
    finally:
        _active_connections -= 1
