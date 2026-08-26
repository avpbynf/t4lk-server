<p align="center">
  <img src="docs/logo.png" width="128" alt="">
</p>

<h1 align="center">Talk Server</h1>

<p align="center">
  Your own GPU, answering the OpenAI transcription API.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-6366f1?style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/inference-faster--whisper-6366f1?style=flat-square" alt="faster-whisper">
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-MIT-6366f1?style=flat-square" alt="MIT"></a>
</p>

---

This is a drop-in replacement for OpenAI's `/v1/audio/transcriptions`. Anything that
already speaks that API points at this server instead, and the inference happens on a
card you own, on audio that never leaves your network. The model is
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), held resident so a request
pays for the transcription and not for the loading.

Nothing is kept. The audio is transcribed and dropped, the text is returned and
forgotten, and the only row written is one usage log per authenticated request carrying
the token, the route, a timestamp and how long it took. History, if you want history,
lives on the client.

It pairs with [Talk-Client](https://github.com/avpbynf/Talk-Client), a Windows desktop
app that dictates into whatever window has focus and falls back to a local engine when
this server is unreachable. Neither needs the other to be useful.

## Quick start

You need an NVIDIA GPU with CUDA, or `DEVICE=cpu` and patience, plus Docker with the
NVIDIA Container Toolkit.

```bash
cp .env.example .env
```

`ADMIN_TOKEN` is the one setting that matters at bootstrap, and `make token` prints a
suitable random string. Leave it empty and the server starts, warns, and answers 401 to
every `/v1` call, which is the single most confusing failure this project has.

```bash
make up
make token-create NAME=laptop
```

Keep the `sk_...` that prints. Tokens are stored hashed, so it is shown once and there
is no recovery path, only revoke and mint again.

```bash
curl -H "Authorization: Bearer sk_..." \
     -F file=@audio.wav \
     http://localhost:8000/v1/audio/transcriptions
```

The first start pulls the model from HuggingFace, so it is slow rather than hung, and
the healthcheck stays red until the model is resident.

## Endpoints

| Method | Path | Auth | What it does |
|---|---|---|---|
| POST | `/v1/audio/transcriptions` | Bearer | Full transcription, OpenAI-compatible |
| POST | `/v1/audio/transcriptions/stream` | Bearer | The same, streamed over SSE |
| GET | `/health` | none | Model state, device, queue depth |
| GET | `/admin/` | `ADMIN_TOKEN` | Token management dashboard |
| * | `/admin/tokens[...]` | `ADMIN_TOKEN` | Token CRUD and per-token usage |

`/health` deliberately needs no token: it is what lets a client probe reachability
before it holds one, and what lets a monitor work without being given a secret.

## Configuration

All of it lives in `.env`.

| Variable | Default | What it does |
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

`GPU_CONCURRENCY` stays at 1 for a reason: one card serialises the work anyway, and
raising it trades latency for an out-of-memory risk you only discover under load.
Requests queue instead, and the queue depth is on `/health`.

Tokens live in SQLite on the `token-data` volume and survive a rebuild.

## Development

```bash
make sync
make dev
```

`make test` runs pytest against an 80% coverage floor, `make lint` runs ruff and mypy,
and `make help` lists everything else.

## Documentation

| Guide | Covers |
|---|---|
| [endpoints.md](docs/guides/endpoints.md) | Route layout, response contracts, error codes, adding an endpoint |
| [debug.md](docs/guides/debug.md) | Diagnosing 503s, invalid audio, CUDA OOM, an unreachable server |
| [monitoring.md](docs/guides/monitoring.md) | Health endpoint, log format, GPU monitoring |
| [testing.md](docs/guides/testing.md) | Fixtures, coverage, naming conventions |

## Licence

MIT, see [LICENSE](LICENSE).
