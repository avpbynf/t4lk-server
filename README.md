# t4lk-server

OpenAI-compatible Speech-to-Text API, GPU-accelerated with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

Drop-in replacement for the OpenAI `/v1/audio/transcriptions` endpoint: point any
client that already speaks that API at this server and it works, with your own GPU
doing the inference and your audio never leaving your machine.

Pairs with [t4lk-client](https://github.com/avpbynf/t4lk-client), a desktop app that
uses this server and falls back to local transcription when it is unreachable.

## Requirements

- NVIDIA GPU with CUDA (or set `DEVICE=cpu`)
- Docker with the NVIDIA Container Toolkit, or Python 3.10+ and [uv](https://docs.astral.sh/uv/)

## Quick start

```bash
cp .env.example .env
```

Set `ADMIN_TOKEN` in `.env` to a random string (`make token` prints one), then:

```bash
make up
```

Mint a token for a machine, and keep the `sk_...` it prints. It is shown once:

```bash
make token-create NAME=laptop
```

Transcribe:

```bash
curl -H "Authorization: Bearer sk_..." -F file=@audio.wav http://localhost:8000/v1/audio/transcriptions
```

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/v1/audio/transcriptions` | Bearer | Full transcription, OpenAI-compatible |
| POST | `/v1/audio/transcriptions/stream` | Bearer | Same, streamed over SSE |
| GET | `/health` | none | Model state, device, queue depth |
| GET | `/admin/` | `ADMIN_TOKEN` | Token management dashboard |
| * | `/admin/tokens[...]` | `ADMIN_TOKEN` | Token CRUD and usage stats |

Every `/v1` route requires a Bearer token. With `ADMIN_TOKEN` unset, `/admin` is
disabled and `/v1` answers 401 to everything, so the server logs a warning at
startup rather than silently serving nothing.

## Configuration

Set in `.env`.

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `Systran/faster-whisper-large-v3` | Model to load |
| `DEVICE` | `cuda` | `cuda` or `cpu` |
| `COMPUTE_TYPE` | `int8_float16` | faster-whisper compute type |
| `GPU_TIMEOUT` | `120` | Seconds a request waits for the GPU |
| `GPU_CONCURRENCY` | `1` | Concurrent GPU requests |
| `DEFAULT_LANGUAGE` | `fr` | Used when the request omits one |
| `CORS_ALLOW_ORIGINS` | `["*"]` | Allowed origins |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/tokens.db` | Token store |
| `ADMIN_TOKEN` | (empty) | Admin credential; empty disables `/admin` |

The model is pulled from HuggingFace on first start, so expect the first run to be
slow. Tokens live in SQLite on the `token-data` volume and survive a rebuild.

## Development

```bash
make sync
make dev
```

`make test` runs pytest (80% coverage floor), `make lint` runs ruff and mypy, and
`make help` lists the rest.

## Documentation

Deeper guides live in [`docs/guides/`](docs/guides), in French:

| Guide | Covers |
|---|---|
| [endpoints.md](docs/guides/endpoints.md) | Route layout, response contracts, error codes, adding an endpoint |
| [debug.md](docs/guides/debug.md) | Diagnosing 503s, invalid audio, CUDA OOM, unreachable server |
| [monitoring.md](docs/guides/monitoring.md) | Health endpoint, log format, GPU monitoring |
| [testing.md](docs/guides/testing.md) | Fixtures, coverage, naming conventions |

## Licence

MIT, see [LICENSE](LICENSE).
