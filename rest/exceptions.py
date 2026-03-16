"""Custom exception hierarchy for the STT server."""


class STTError(Exception):
    """Base exception for STT errors."""

    def __init__(self, message: str) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable error description.
        """
        super().__init__(message)
        self.message = message


class TranscriptionError(STTError):
    """Raised when transcription fails."""

    def __init__(self, message: str) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable error description.
        """
        super().__init__(message)


class QueueTimeoutError(STTError):
    """Raised when GPU queue timeout is exceeded."""

    def __init__(self, message: str) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable error description.
        """
        super().__init__(message)


class InvalidAudioError(STTError):
    """Raised when uploaded audio file is invalid."""

    def __init__(self, message: str) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable error description.
        """
        super().__init__(message)
