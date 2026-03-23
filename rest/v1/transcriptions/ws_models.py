"""Pydantic models for the T4lk WebSocket protocol messages."""

from pydantic import BaseModel, ConfigDict


class WsConnectedMessage(BaseModel):
    """Server -> client: connection established."""

    model_config = ConfigDict(frozen=True)

    type: str = "connected"
    server_version: str
    max_duration: int


class WsReadyMessage(BaseModel):
    """Server -> client: session ready, send audio."""

    model_config = ConfigDict(frozen=True)

    type: str = "ready"


class WsSegmentMessage(BaseModel):
    """Server -> client: a transcribed segment."""

    model_config = ConfigDict(frozen=True)

    type: str = "segment"
    index: int
    start: float
    end: float
    text: str


class WsDoneMessage(BaseModel):
    """Server -> client: transcription complete."""

    model_config = ConfigDict(frozen=True)

    type: str = "done"
    text: str
    language: str
    duration: float


class WsErrorMessage(BaseModel):
    """Server -> client: error occurred."""

    model_config = ConfigDict(frozen=True)

    type: str = "error"
    code: str
    message: str


class WsCancelledMessage(BaseModel):
    """Server -> client: session cancelled."""

    model_config = ConfigDict(frozen=True)

    type: str = "cancelled"
