"""Tests for transcription endpoints: POST /v1/audio/transcriptions and /health."""

import json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WAV_BYTES = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00"
    b"\x02\x00\x10\x00data\x00\x00\x00\x00"
)


def _audio_file(filename: str = "test.wav", content: bytes = _WAV_BYTES):
    """Return a files dict suitable for httpx multipart upload."""
    return {"file": (filename, content, "audio/wav")}


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200


async def test_health_response_model_loaded(client):
    data = (await client.get("/health")).json()
    assert data["model_loaded"] is True


async def test_health_response_status_ok(client):
    data = (await client.get("/health")).json()
    assert data["status"] == "ok"


async def test_health_response_has_queue_size(client):
    data = (await client.get("/health")).json()
    assert "queue_size" in data
    assert data["queue_size"] >= 0


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions, response_format=json (default)
# ---------------------------------------------------------------------------


async def test_transcription_json_format_status_200(client):
    response = await client.post("/v1/audio/transcriptions", files=_audio_file())
    assert response.status_code == 200


async def test_transcription_json_format_text_field(client):
    response = await client.post("/v1/audio/transcriptions", files=_audio_file())
    data = response.json()

    assert "text" in data
    assert "Bonjour" in data["text"]
    assert "tout le monde" in data["text"]


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions, response_format=text
# ---------------------------------------------------------------------------


async def test_transcription_text_format_returns_plain_text(client):
    response = await client.post(
        "/v1/audio/transcriptions",
        files=_audio_file(),
        data={"response_format": "text"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "Bonjour" in response.text


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions, response_format=verbose_json
# ---------------------------------------------------------------------------


async def test_transcription_verbose_json_format(client):
    response = await client.post(
        "/v1/audio/transcriptions",
        files=_audio_file(),
        data={"response_format": "verbose_json"},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["task"] == "transcribe"
    assert data["language"] == "fr"
    assert data["duration"] == 5.0
    assert "text" in data
    assert isinstance(data["segments"], list)
    assert len(data["segments"]) == 2


async def test_transcription_verbose_json_segment_fields(client):
    response = await client.post(
        "/v1/audio/transcriptions",
        files=_audio_file(),
        data={"response_format": "verbose_json"},
    )
    seg = response.json()["segments"][0]

    assert "index" in seg
    assert "start" in seg
    assert "end" in seg
    assert "text" in seg


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions, response_format=srt
# ---------------------------------------------------------------------------


async def test_transcription_srt_format(client):
    response = await client.post(
        "/v1/audio/transcriptions",
        files=_audio_file(),
        data={"response_format": "srt"},
    )

    assert response.status_code == 200
    text = response.text
    # SRT starts with a sequence number
    assert text.strip().startswith("1")
    # Contains timecode separator
    assert " --> " in text


async def test_transcription_srt_timecode_format(client):
    response = await client.post(
        "/v1/audio/transcriptions",
        files=_audio_file(),
        data={"response_format": "srt"},
    )
    # SRT timecodes use comma as millisecond separator: HH:MM:SS,mmm
    assert "," in response.text


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions, response_format=vtt
# ---------------------------------------------------------------------------


async def test_transcription_vtt_format(client):
    response = await client.post(
        "/v1/audio/transcriptions",
        files=_audio_file(),
        data={"response_format": "vtt"},
    )

    assert response.status_code == 200
    text = response.text
    assert text.startswith("WEBVTT")
    assert " --> " in text


async def test_transcription_vtt_timecode_uses_dot(client):
    response = await client.post(
        "/v1/audio/transcriptions",
        files=_audio_file(),
        data={"response_format": "vtt"},
    )
    # VTT timecodes use dot as millisecond separator: HH:MM:SS.mmm
    lines = [ln for ln in response.text.splitlines() if "-->" in ln]
    assert len(lines) > 0
    assert "." in lines[0]


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions, validation errors
# ---------------------------------------------------------------------------


async def test_transcription_invalid_extension_returns_400(client):
    # Arrange: upload a .exe file
    response = await client.post(
        "/v1/audio/transcriptions",
        files={"file": ("malware.exe", b"fake data", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "message" in response.json()


async def test_transcription_oversized_file_returns_400(client):
    # Arrange: create a bytes object larger than MAX_UPLOAD_SIZE (25 MB)
    big_data = b"x" * (25 * 1024 * 1024 + 1)
    response = await client.post(
        "/v1/audio/transcriptions",
        files={"file": ("big.wav", big_data, "audio/wav")},
    )

    assert response.status_code == 400
    assert "message" in response.json()


async def test_transcription_invalid_response_format_returns_400(client):
    response = await client.post(
        "/v1/audio/transcriptions",
        files=_audio_file(),
        data={"response_format": "docx"},
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions/stream
# ---------------------------------------------------------------------------


async def test_transcription_stream_returns_200(client):
    response = await client.post(
        "/v1/audio/transcriptions/stream",
        files=_audio_file(),
    )
    assert response.status_code == 200


async def test_transcription_stream_content_type_is_event_stream(client):
    response = await client.post(
        "/v1/audio/transcriptions/stream",
        files=_audio_file(),
    )
    assert "text/event-stream" in response.headers["content-type"]


async def test_transcription_stream_yields_segment_events(client):
    response = await client.post(
        "/v1/audio/transcriptions/stream",
        files=_audio_file(),
    )
    raw = response.text
    assert "event: segment" in raw


async def test_transcription_stream_yields_done_event(client):
    response = await client.post(
        "/v1/audio/transcriptions/stream",
        files=_audio_file(),
    )
    assert "event: done" in response.text


async def test_transcription_stream_segment_data_is_valid_json(client):
    response = await client.post(
        "/v1/audio/transcriptions/stream",
        files=_audio_file(),
    )
    lines = response.text.splitlines()
    data_lines = [ln for ln in lines if ln.startswith("data:") and "event" not in ln]
    # Parse at least one data line
    assert len(data_lines) > 0
    payload = json.loads(data_lines[0].removeprefix("data: "))
    assert isinstance(payload, dict)


async def test_transcription_stream_done_event_has_text(client):
    response = await client.post(
        "/v1/audio/transcriptions/stream",
        files=_audio_file(),
    )
    lines = response.text.splitlines()
    # Find the data line after "event: done"
    done_data = None
    for i, line in enumerate(lines):
        if line == "event: done" and i + 1 < len(lines):
            done_data = lines[i + 1].removeprefix("data: ")
            break

    assert done_data is not None
    payload = json.loads(done_data)
    assert "text" in payload
    assert "language" in payload
    assert "duration" in payload


async def test_transcription_stream_invalid_extension_returns_400(client):
    response = await client.post(
        "/v1/audio/transcriptions/stream",
        files={"file": ("bad.xyz", b"data", "application/octet-stream")},
    )
    assert response.status_code == 400
