# Troubleshooting guide

Diagnosing and fixing t4lk-server (FastAPI + CUDA), including the case where a client
cannot reach it.

---

## First look

Run these before anything else:

```bash
docker ps      # are the containers up
make logs      # follow the server logs
make health    # does the API answer
```

`make health` calls `GET /health`. A `200 OK` carrying
`{"status": "ok", "model_loaded": true}` means the server is serving. Anything else, or
a timeout, means it is not.

---

## FastAPI diagnostics

### Swagger

In development the interactive docs are at:

```
http://localhost:8000/docs
```

Every endpoint can be exercised there without another client. ReDoc is at
`http://localhost:8000/redoc`.

### Request tracing

`AccessLogMiddleware` in `rest/middlewares.py` logs one line per request, with method,
path, status, duration and the transcription metadata:

```
2026-03-16 10:00:00 [INFO] rest.middlewares: POST /v1/audio/transcriptions 200 1234.5ms
[trace_id=abc123def456 audio=5000ms model=large-v3 lang=fr queue=0ms]
```

Every response also carries `X-Request-Id`, which is what correlates a client report
with a server log line.

To reproduce a request outside the client (every `/v1` call needs a token):

```bash
# Plain transcription
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer sk_..." \
  -F "file=@/path/to/audio.wav" \
  -F "language=fr"

# verbose_json, with segments and duration
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer sk_..." \
  -F "file=@/path/to/audio.wav" \
  -F "response_format=verbose_json"

# The SSE route
curl -X POST http://localhost:8000/v1/audio/transcriptions/stream \
  -H "Authorization: Bearer sk_..." \
  -H "Accept: text/event-stream" \
  -F "file=@/path/to/audio.wav"
```

### Uvicorn logs

```bash
make logs
docker logs t4lk-server --follow --tail 100
```

---

## Common failures

### 401 -- every call is rejected

**Symptom**: every `/v1` request answers `401`, including ones that worked before.

**Likely causes**:

1. `ADMIN_TOKEN` is empty. That disables `/admin` and locks `/v1` to 401 for everything.
   A warning is logged at startup; this is the first thing to check.
2. The token was revoked, or the client is sending a stale one.
3. The header is malformed. It must be `Authorization: Bearer sk_...`.

**Checks**:

```bash
make logs | grep -i "admin_token\|auth\|401"
make token-create NAME=debug     # mint a fresh one and retry
```

---

### 503 -- model not loaded, or GPU timeout

**Symptom**: `POST /v1/audio/transcriptions` answers `503 Service Unavailable`.

**Likely causes**:

1. The model is still loading. faster-whisper takes 30 to 60 seconds at startup, and
   longer on the very first run while the weights download.
2. `WHISPER_MODEL` names a model that does not exist or cannot be reached.
3. CUDA failed to initialise (see the out-of-memory section below).
4. The request waited longer than `GPU_TIMEOUT` for a GPU slot, because too many
   requests are in flight.

**Checks**:

```bash
make health                                        # retry until model_loaded is true
make logs | grep -i "model\|whisper\|load\|timeout"
grep WHISPER_MODEL .env
```

---

### 400 -- invalid audio file

**Symptom**: `POST /v1/audio/transcriptions` answers `400 Bad Request`.

**Likely causes**:

1. Unsupported extension. Only `wav`, `mp3`, `mp4`, `m4a`, `ogg`, `flac` and `webm` are
   accepted.
2. The file is larger than 25 MB.
3. `response_format` is not one of the supported values.

The `detail` field of the response says which one it was.

---

### CUDA out of memory

**Symptom**: `CUDA out of memory` in the logs, followed by a `503` or a dead process.

**Likely causes**:

1. Another process holds the GPU memory, often a second instance of the server.
2. The chosen model does not fit the available VRAM.
3. Concurrent transcriptions together exceed it.

**Checks**:

```bash
nvidia-smi                              # overall GPU state
nvidia-smi pmon -s m                    # which processes hold memory
make logs | grep -i "cuda\|memory\|oom"
```

**Fixes**:

- Use a smaller model (`WHISPER_MODEL=medium` rather than `large-v3`) in `.env`, then
  `make restart`.
- Stop the other CUDA processes.
- Keep `GPU_CONCURRENCY` at 1. Raising it on a single card trades latency for OOM risk.

---

### The client cannot reach the server

**Symptom**: the client reports a connection error or a timeout, while curl against the
same server works.

**Likely causes**:

1. The server URL configured in the client is wrong: wrong host, wrong port, or `http`
   where the server expects `https`.
2. Uvicorn is bound to `127.0.0.1` rather than `0.0.0.0`, so nothing outside the
   container or the machine can reach it.
3. A firewall or network policy blocks the port.
4. CORS. A Tauri client is its own origin.

**Checks**:

```bash
curl http://localhost:8000/health          # from the machine running the client
make logs | grep "Uvicorn running on"      # which address it bound to
docker inspect t4lk-server | grep -A 10 '"Ports"'
```

**CORS**: `CORS_ALLOW_ORIGINS` in `.env` defaults to `*`. To narrow it, list the origins
separated by commas:

```env
CORS_ALLOW_ORIGINS=tauri://localhost,http://localhost,https://localhost
```

It is read in `rest/settings.py` and applied in `rest/main.py`.

---

## Makefile targets used while debugging

| Target | Description |
|---|---|
| `make health` | Calls `GET /health` |
| `make logs` | Follows the logs |
| `make gpu` | GPU state via nvidia-smi |
| `make restart` | Restarts the server without rebuilding the image |
| `make down` | Stops the Docker services |
| `make up` | Starts them, rebuilding the image |
| `make token-create` | Mints an API token: `make token-create NAME=<machine>` |
