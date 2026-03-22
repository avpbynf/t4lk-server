"""Whisper engine module — manages the faster-whisper model and GPU access."""

import asyncio
import io
import logging
import time
from dataclasses import dataclass, field

from faster_whisper import WhisperModel

from rest.exceptions import QueueTimeoutError, TranscriptionError
from rest.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SegmentResult:
    """A single transcription segment.

    Attributes:
        index: Zero-based segment index.
        start: Segment start time in seconds.
        end: Segment end time in seconds.
        text: Transcribed text for this segment.
    """

    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    """Result of a transcription operation.

    Attributes:
        text: Full concatenated transcription text.
        language: Detected or requested language code.
        duration: Audio duration in seconds.
        segments: Ordered list of transcription segments.
    """

    text: str
    language: str
    duration: float
    segments: list[SegmentResult] = field(default_factory=list)


class WhisperEngine:
    """Manages the Whisper model and GPU queue.

    Provides transcription with GPU concurrency control via asyncio.Semaphore.
    The model is loaded once at startup and reused for all requests.

    Args:
        settings: Application settings instance.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the engine with settings and concurrency semaphore.

        Args:
            settings: Application settings instance.
        """
        self._settings = settings
        self._model: WhisperModel | None = None
        self._semaphore = asyncio.Semaphore(settings.GPU_CONCURRENCY)

    async def load(self) -> None:
        """Load the Whisper model. Called during app startup.

        Loads the model in a thread pool to avoid blocking the event loop.
        Raises an exception if loading fails — the server should not start
        with an unloaded model.

        Raises:
            Exception: If model loading fails for any reason.
        """
        logger.info(
            "Loading Whisper model '%s' on device '%s'",
            self._settings.WHISPER_MODEL,
            self._settings.DEVICE,
        )
        try:
            self._model = await asyncio.to_thread(
                WhisperModel,
                self._settings.WHISPER_MODEL,
                device=self._settings.DEVICE,
                compute_type=self._settings.COMPUTE_TYPE,
            )
            logger.info(
                "Whisper model '%s' loaded on %s",
                self._settings.WHISPER_MODEL,
                self._settings.DEVICE,
            )
        except Exception:
            logger.exception(
                "Failed to load Whisper model '%s'", self._settings.WHISPER_MODEL
            )
            raise

    def unload(self) -> None:
        """Unload the model. Called during app shutdown."""
        if self._model is not None:
            del self._model
            self._model = None
            import gc

            gc.collect()
            logger.info("Whisper model unloaded and garbage collected")
        else:
            logger.info("No model to unload")

    @property
    def is_loaded(self) -> bool:
        """Return True if the model is currently loaded."""
        return self._model is not None

    @property
    def queue_size(self) -> int:
        """Return the number of requests waiting for GPU access."""
        return max(0, self._settings.GPU_CONCURRENCY - self._semaphore._value)

    async def transcribe(
        self,
        audio_data: bytes,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio data with GPU queue management.

        Acquires the GPU semaphore with a timeout, then runs the model in a
        thread pool to avoid blocking the event loop.

        Args:
            audio_data: Raw audio bytes to transcribe.
            language: Optional BCP-47 language code. Auto-detected if None.
            prompt: Optional initial prompt to guide the transcription.

        Returns:
            TranscriptionResult with text, language, duration, and segments.

        Raises:
            QueueTimeoutError: If the GPU queue timeout is exceeded.
            TranscriptionError: If transcription fails.
        """
        queue_start = time.perf_counter()
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._settings.GPU_TIMEOUT,
            )
        except TimeoutError:
            raise QueueTimeoutError(
                f"GPU queue timeout exceeded after {self._settings.GPU_TIMEOUT}s"
            )

        queue_wait_ms = (time.perf_counter() - queue_start) * 1000

        try:
            result = await asyncio.to_thread(
                self._transcribe_sync, audio_data, language, prompt
            )
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"Transcription failed: {exc}") from exc
        finally:
            self._semaphore.release()

        logger.debug(
            "Transcription complete: language=%s duration=%.2fs queue_wait=%.1fms",
            result.language,
            result.duration,
            queue_wait_ms,
        )
        return result

    def _transcribe_sync(
        self,
        audio_data: bytes,
        language: str | None,
        prompt: str | None,
    ) -> TranscriptionResult:
        """Synchronous transcription, intended to run in a thread pool.

        Args:
            audio_data: Raw audio bytes.
            language: Optional language code.
            prompt: Optional initial prompt.

        Returns:
            TranscriptionResult with all segments populated.

        Raises:
            TranscriptionError: If the model is not loaded or transcription fails.
        """
        if self._model is None:
            raise TranscriptionError("Whisper model is not loaded")

        try:
            with io.BytesIO(audio_data) as audio_stream:
                segments_iter, info = self._model.transcribe(
                    audio_stream,
                    language=language,
                    initial_prompt=prompt,
                    vad_filter=True,
                )
                segments = [
                    SegmentResult(
                        index=i,
                        start=seg.start,
                        end=seg.end,
                        text=seg.text,
                    )
                    for i, seg in enumerate(segments_iter)
                ]
        except Exception as exc:
            raise TranscriptionError(f"Model transcription failed: {exc}") from exc

        text = "".join(seg.text for seg in segments).strip()
        return TranscriptionResult(
            text=text,
            language=info.language,
            duration=info.duration,
            segments=segments,
        )

    async def transcribe_stream(
        self,
        audio_data: bytes,
        language: str | None = None,
        prompt: str | None = None,
    ):
        """Streaming transcription — yields segments as they are produced.

        Acquires the GPU semaphore with a timeout, runs the full transcription
        in a thread pool (since faster-whisper's iterator is synchronous), then
        yields each SegmentResult followed by a final TranscriptionResult.

        Args:
            audio_data: Raw audio bytes to transcribe.
            language: Optional BCP-47 language code. Auto-detected if None.
            prompt: Optional initial prompt to guide the transcription.

        Yields:
            SegmentResult for each transcribed segment, then a final
            TranscriptionResult summarising the full transcription.

        Raises:
            QueueTimeoutError: If the GPU queue timeout is exceeded.
            TranscriptionError: If transcription fails.
        """
        queue_start = time.perf_counter()
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._settings.GPU_TIMEOUT,
            )
        except TimeoutError:
            raise QueueTimeoutError(
                f"GPU queue timeout exceeded after {self._settings.GPU_TIMEOUT}s"
            )

        queue_wait_ms = (time.perf_counter() - queue_start) * 1000

        try:
            result = await asyncio.to_thread(
                self._transcribe_sync, audio_data, language, prompt
            )
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"Transcription failed: {exc}") from exc
        finally:
            self._semaphore.release()

        logger.debug(
            "Stream complete: lang=%s dur=%.2fs queue=%.1fms",
            result.language,
            result.duration,
            queue_wait_ms,
        )

        for segment in result.segments:
            yield segment

        yield result
