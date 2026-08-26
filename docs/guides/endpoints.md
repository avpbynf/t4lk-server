# Endpoint guide

Interface conventions and active contracts for the t4lk-server endpoints.

---

## Route layout

Every `/v1` route is behind a Bearer token. The layout is deliberately flat and
mirrors the OpenAI Audio API:

```
HTTP client
    |
    v
rest/main.py        <-- application factory, health endpoint
    |
    +-- rest/routes.py          versioned router (/v1 prefix)
    |    +-- rest/v1/transcriptions/router.py   transcription endpoints
    +-- rest/admin/routes.py    token dashboard and CRUD
```

Where a new endpoint goes:

- health (`/health`) belongs in `rest/main.py`
- transcription (`/v1/audio/transcriptions*`) belongs in `rest/v1/transcriptions/router.py`
- token management (`/admin/*`) belongs in `rest/admin/routes.py`

---

## Conventions

### Authentication

Every `/v1` route requires a Bearer token (`Authorization: Bearer sk_...`). Tokens are
minted by the administrator, stored hashed, and revocable per machine. The `/admin`
routes are guarded separately by `ADMIN_TOKEN`. Only `/health` stays open, so probes
can answer without holding a secret.

An empty `ADMIN_TOKEN` disables `/admin` and locks `/v1` to 401. A warning is logged at
startup, and that is the first place to look when everything answers 401.

### Audio upload

Transcription endpoints take the audio as `multipart/form-data`. The field is named
`file` and must be an `UploadFile`.

```python
@router.post("/transcriptions")
async def create_transcription(file: UploadFile = File(...)):
    ...
```

Supported formats: `wav`, `mp3`, `mp4`, `m4a`, `ogg`, `flac`, `webm`. Maximum size 25 MB.

### Response format

The `response_format` parameter drives what comes back:

| Value | Content type | Description |
|---|---|---|
| `json` (default) | `application/json` | `{"text": "..."}` |
| `verbose_json` | `application/json` | Text, language, duration, segments |
| `text` | `text/plain` | Raw transcription |
| `srt` | `text/plain` | SRT subtitles |
| `vtt` | `text/plain` | WebVTT subtitles |

Errors use the standard FastAPI shape:

```json
{ "detail": "what went wrong" }
```

The SSE route (`/v1/audio/transcriptions/stream`) returns a `text/event-stream`.

### Response headers

Every response carries tracing and timing headers:

| Header | Description |
|---|---|
| `X-Request-Id` | Unique request identifier (16 hex bytes) |
| `X-Execution-Time` | Total processing time in ms, e.g. `1234.5ms` |

---

## Active contracts

### 1. POST /v1/audio/transcriptions

| Property | Value |
|---|---|
| Method | `POST` |
| Path | `/v1/audio/transcriptions` |
| Auth | Bearer token |
| Content-Type | `multipart/form-data` |

Form fields:

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | `UploadFile` | yes | -- | Audio file |
| `model` | `str` | no | -- | Informational only; the configured model is used |
| `language` | `str` | no | `DEFAULT_LANGUAGE` | BCP-47 code (`fr`, `en`, ...) |
| `response_format` | `str` | no | `json` | See the table above |
| `temperature` | `float` | no | `0.0` | Sampling temperature |
| `prompt` | `str` | no | -- | Initial prompt, to steer the transcription |

Default `json` response:

```json
{"text": "Bonjour comment allez-vous"}
```

`verbose_json` response:

```json
{
  "task": "transcribe",
  "language": "fr",
  "duration": 5.1,
  "text": "Bonjour comment allez-vous",
  "segments": [
    {"index": 0, "start": 0.0, "end": 2.5, "text": " Bonjour"},
    {"index": 1, "start": 2.5, "end": 5.1, "text": " comment allez-vous"}
  ]
}
```

---

### 2. POST /v1/audio/transcriptions/stream

| Property | Value |
|---|---|
| Method | `POST` |
| Path | `/v1/audio/transcriptions/stream` |
| Auth | Bearer token |
| Content-Type | `multipart/form-data` |
| Response | `200` `text/event-stream` (SSE) |

Same form fields as the endpoint above, minus `response_format`.

Event shape:

```
event: segment
data: {"index": 0, "start": 0.0, "end": 2.5, "text": " Bonjour"}

event: segment
data: {"index": 1, "start": 2.5, "end": 5.1, "text": " comment allez-vous"}

event: done
data: {"text": "Bonjour comment allez-vous", "language": "fr", "duration": 5.1}
```

When a failure happens after the stream has started:

```
event: error
data: {"message": "GPU queue timeout exceeded after 120s", "type": "QueueTimeoutError"}
```

This route is an extension; the OpenAI API has no equivalent.

---

### 3. GET /health

| Property | Value |
|---|---|
| Method | `GET` |
| Path | `/health` |
| Auth | none |
| Response | `200` JSON |

```json
{
  "status": "ok",
  "model_loaded": true,
  "device": "cuda",
  "queue_size": 0
}
```

`status` is `"ok"` once the model is loaded and `"degraded"` before that. `queue_size`
is how many requests are waiting for a GPU slot.

---

### 4. /admin

| Property | Value |
|---|---|
| Path | `/admin/` and `/admin/tokens[...]` |
| Auth | `ADMIN_TOKEN` |

`/admin/` serves the HTML dashboard. Under `/admin/tokens` sit the create, list, read,
delete and per-token usage endpoints. A minted token is shown once and stored hashed,
so there is no recovery path, only revoke and mint again.

---

## HTTP error codes

| Code | Exception | Cause |
|---|---|---|
| `400` | `InvalidAudioError` | Bad file format or size, unsupported response format |
| `401` | -- | Missing, malformed or revoked Bearer token |
| `422` | FastAPI validation | Missing or mistyped form field |
| `500` | `TranscriptionError` | The model failed to transcribe |
| `503` | `QueueTimeoutError` | Waited longer than `GPU_TIMEOUT` for the GPU |

---

## Adding an endpoint

### A transcription endpoint

Add it to `rest/v1/transcriptions/router.py`, following the existing pattern:

```python
@router.get("/transcriptions/{id}")
async def get_transcription(
    id: str,
    request: Request,
):
    engine = _get_engine(request)
    # implementation
    return {"id": id}
```

### A new versioned endpoint

Create a sub-package under `rest/v1/` and include its router from `rest/routes.py`:

```python
from rest.v1.newthing.router import router as newthing_router
router.include_router(newthing_router)
```

### Before merging

- [ ] The endpoint is documented here, under "Active contracts"
- [ ] Input is validated before anything touches the GPU
- [ ] Error responses are tested (400, 401, 422, 500, 503)
- [ ] A unit or integration test covers it
- [ ] Overall coverage stays above 80%
