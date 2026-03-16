"""Pydantic models for transcription endpoints."""

from pydantic import BaseModel, ConfigDict

MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {"wav", "mp3", "mp4", "m4a", "ogg", "flac", "webm"}
ALLOWED_RESPONSE_FORMATS = {"json", "text", "verbose_json", "srt", "vtt"}


class SegmentInfo(BaseModel):
    """A single transcription segment with timing information."""

    model_config = ConfigDict(frozen=True)

    index: int
    start: float
    end: float
    text: str


class TranscriptionResponse(BaseModel):
    """Plain JSON transcription response."""

    model_config = ConfigDict(frozen=True)

    text: str


class VerboseTranscriptionResponse(BaseModel):
    """Verbose JSON transcription response with segment details."""

    model_config = ConfigDict(frozen=True)

    task: str
    language: str
    duration: float
    text: str
    segments: list[SegmentInfo]


class StreamSegmentEvent(BaseModel):
    """SSE event payload for a transcribed segment."""

    model_config = ConfigDict(frozen=True)

    index: int
    start: float
    end: float
    text: str


class StreamDoneEvent(BaseModel):
    """SSE event payload signalling end of stream."""

    model_config = ConfigDict(frozen=True)

    text: str
    language: str
    duration: float


class StreamErrorEvent(BaseModel):
    """SSE event payload for a stream error."""

    model_config = ConfigDict(frozen=True)

    message: str
    type: str
