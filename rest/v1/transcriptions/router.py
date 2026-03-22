"""FastAPI router for transcription endpoints (OpenAI-compatible)."""

import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse

from rest.engine import TranscriptionResult, WhisperEngine
from rest.exceptions import InvalidAudioError
from rest.settings import get_settings
from rest.v1.transcriptions.models import (
    ALLOWED_EXTENSIONS,
    ALLOWED_RESPONSE_FORMATS,
    MAX_UPLOAD_SIZE,
    SegmentInfo,
    StreamDoneEvent,
    StreamErrorEvent,
    StreamSegmentEvent,
    TranscriptionResponse,
    VerboseTranscriptionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["transcriptions"])


def _validate_upload(file: UploadFile, content: bytes) -> None:
    """Validate uploaded audio file.

    Checks file size and extension before GPU semaphore acquisition.

    Args:
        file: The uploaded file object (used to read filename/extension).
        content: The raw bytes already read from the upload.

    Raises:
        InvalidAudioError: If file size exceeds MAX_UPLOAD_SIZE or extension
            is not in ALLOWED_EXTENSIONS.
    """
    if len(content) > MAX_UPLOAD_SIZE:
        raise InvalidAudioError(
            f"File size {len(content)} bytes exceeds maximum of {MAX_UPLOAD_SIZE} bytes"
        )

    filename = file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise InvalidAudioError(
            f"File extension '{extension}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )


def _get_engine(request: Request) -> WhisperEngine:
    """Get WhisperEngine from app state.

    Args:
        request: The current FastAPI request.

    Returns:
        WhisperEngine: The loaded engine instance.
    """
    engine: WhisperEngine = request.app.state.engine
    return engine


def _format_srt(segments: list[SegmentInfo]) -> str:
    """Format segments as SRT subtitles.

    Args:
        segments: List of transcription segments with timing.

    Returns:
        SRT-formatted subtitle string.
    """

    def _ts(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    lines: list[str] = []
    for seg in segments:
        lines.append(str(seg.index + 1))
        lines.append(f"{_ts(seg.start)} --> {_ts(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines)


def _format_vtt(segments: list[SegmentInfo]) -> str:
    """Format segments as WebVTT subtitles.

    Args:
        segments: List of transcription segments with timing.

    Returns:
        WebVTT-formatted subtitle string.
    """

    def _ts(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

    lines: list[str] = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_ts(seg.start)} --> {_ts(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines)


@router.post("/transcriptions")
async def create_transcription(
    request: Request,
    file: UploadFile = File(...),
    model: str | None = Form(None),
    language: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
    prompt: str | None = Form(None),
):
    """Create a transcription (OpenAI-compatible).

    Accepts multipart/form-data with an audio file and optional parameters.
    Returns the transcription in the requested format.

    STT-specific metadata is stored in request.state for AccessLogMiddleware:
    - request.state.audio_duration_ms
    - request.state.model
    - request.state.language
    - request.state.queue_wait_ms

    Args:
        request: The current FastAPI request.
        file: Audio file upload.
        model: Whisper model name (informational, engine uses configured model).
        language: BCP-47 language code. Falls back to DEFAULT_LANGUAGE if None.
        response_format: One of json, text, verbose_json, srt, vtt.
        temperature: Sampling temperature (0.0 = greedy).
        prompt: Optional initial prompt to guide transcription.

    Returns:
        Transcription response in the requested format.

    Raises:
        InvalidAudioError: If file validation fails.
    """
    settings = get_settings()

    if response_format not in ALLOWED_RESPONSE_FORMATS:
        raise InvalidAudioError(
            f"Response format '{response_format}' is not supported. "
            f"Allowed: {', '.join(sorted(ALLOWED_RESPONSE_FORMATS))}"
        )

    content = await file.read()
    _validate_upload(file, content)

    resolved_language = language or settings.DEFAULT_LANGUAGE
    engine = _get_engine(request)

    result: TranscriptionResult = await engine.transcribe(
        audio_data=content,
        language=resolved_language,
        prompt=prompt,
    )
    del content

    request.state.audio_duration_ms = int(result.duration * 1000)
    request.state.model = model or settings.WHISPER_MODEL
    request.state.language = result.language

    if response_format == "text":
        return PlainTextResponse(result.text)

    if response_format == "verbose_json":
        segments = [
            SegmentInfo(
                index=seg.index,
                start=seg.start,
                end=seg.end,
                text=seg.text,
            )
            for seg in result.segments
        ]
        return VerboseTranscriptionResponse(
            task="transcribe",
            language=result.language,
            duration=result.duration,
            text=result.text,
            segments=segments,
        )

    if response_format == "srt":
        segments = [
            SegmentInfo(index=seg.index, start=seg.start, end=seg.end, text=seg.text)
            for seg in result.segments
        ]
        return PlainTextResponse(_format_srt(segments))

    if response_format == "vtt":
        segments = [
            SegmentInfo(index=seg.index, start=seg.start, end=seg.end, text=seg.text)
            for seg in result.segments
        ]
        return PlainTextResponse(_format_vtt(segments))

    # Default: "json"
    return TranscriptionResponse(text=result.text)


@router.post("/transcriptions/stream")
async def create_transcription_stream(
    request: Request,
    file: UploadFile = File(...),
    model: str | None = Form(None),
    language: str | None = Form(None),
    temperature: float = Form(0.0),
    prompt: str | None = Form(None),
):
    """Create a streaming transcription (YZ extension, not OpenAI standard).

    Accepts multipart/form-data with an audio file and returns an SSE stream.
    Each segment is emitted as it is produced. A final done event summarises
    the full transcription.

    SSE event format:

        event: segment
        data: {"index": 0, "start": 0.0, "end": 2.5, "text": "Bonjour"}

        event: done
        data: {"text": "Full text", "language": "french", "duration": 5.1}

        event: error  (only if an error occurs after the stream has started)
        data: {"message": "GPU timeout", "type": "QueueTimeoutError"}

    Args:
        request: The current FastAPI request.
        file: Audio file upload.
        model: Whisper model name (informational).
        language: BCP-47 language code. Falls back to DEFAULT_LANGUAGE if None.
        temperature: Sampling temperature (0.0 = greedy).
        prompt: Optional initial prompt to guide transcription.

    Returns:
        StreamingResponse with SSE content type.

    Raises:
        InvalidAudioError: If file validation fails before streaming begins.
    """
    settings = get_settings()

    content = await file.read()
    _validate_upload(file, content)

    resolved_language = language or settings.DEFAULT_LANGUAGE
    engine = _get_engine(request)

    async def _event_generator():
        """Yield SSE-formatted events for each segment and final done event."""
        nonlocal content
        try:
            from rest.engine import SegmentResult, TranscriptionResult

            stream = engine.transcribe_stream(
                audio_data=content,
                language=resolved_language,
                prompt=prompt,
            )
            content = None

            async for item in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected, stopping SSE stream")
                    return
                if isinstance(item, SegmentResult):
                    event = StreamSegmentEvent(
                        index=item.index,
                        start=item.start,
                        end=item.end,
                        text=item.text,
                    )
                    yield f"event: segment\ndata: {event.model_dump_json()}\n\n"
                elif isinstance(item, TranscriptionResult):
                    done = StreamDoneEvent(
                        text=item.text,
                        language=item.language,
                        duration=item.duration,
                    )
                    yield f"event: done\ndata: {done.model_dump_json()}\n\n"
        except Exception as exc:
            error = StreamErrorEvent(
                message=str(exc),
                type=type(exc).__name__,
            )
            yield f"event: error\ndata: {error.model_dump_json()}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
