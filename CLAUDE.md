# t4lk-server

FastAPI Speech-to-Text server, OpenAI-compatible, faster-whisper on CUDA.
See [README.md](README.md) for endpoints, configuration and quick start.

## Commands

```bash
make sync    # sync deps via uv
make dev     # uvicorn with reload
make test    # pytest, 80% coverage floor
make lint    # ruff format + ruff check + mypy
make up      # docker compose up -d --build
make logs    # follow container logs
make help    # everything else
```

Run `make lint` and `make test` before committing. Run `make sync` after touching
dependencies. `make up` rebuilds the image, which is what picks up new deps.

## Layout

- `rest/main.py` builds the app and owns `/health`
- `rest/v1/transcriptions/` is the OpenAI-compatible surface
- `rest/admin/` is the token dashboard and CRUD
- `rest/settings.py` holds pydantic-settings config
- `tests/` mirrors `rest/`

## Conventions

- English in code and docstrings, Google style
- Pydantic models are frozen (`frozen: True`), never mutated
- Logging to stdout only, via `logging.getLogger(__name__)`
- Conventional Commits
- Design specs go in `docs/specs/YYYY-MM-DD-<topic>-design.md` and are deleted once
  the work ships, so nothing describes a feature that no longer matches the code

## Things that bite

- A single GPU serialises work. `GPU_CONCURRENCY` defaults to 1 and requests queue
  behind `GPU_TIMEOUT`; raising concurrency on one card trades latency for OOM risk.
- `ADMIN_TOKEN` unset is a valid but useless state: `/admin` is off and every `/v1`
  route answers 401. The startup warning is the only clue, so check it first when
  auth "mysteriously" fails.
- Minted tokens are shown once and stored hashed. There is no recovery path, only
  revoke and re-mint.
- The model downloads from HuggingFace on first start. A cold container is slow, not
  hung.
