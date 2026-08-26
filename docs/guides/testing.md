# Testing guide

What the suite gives you before you write a test: the fixtures that already exist, and
what they stand in for.

---

## Running

```bash
make test
```

That is `pytest --cov=rest --cov-report=term-missing --cov-fail-under=80`, so the
coverage floor lives in the `Makefile` rather than in `pyproject.toml`, which only sets
`testpaths` and `asyncio_mode = "auto"`. Auto mode is why no test carries an
`@pytest.mark.asyncio`: forget that, and an async test written elsewhere silently
passes without ever being awaited.

`tests/` mirrors `rest/`, one `test_<module>.py` per module.

## The fixtures

They chain, so asking for `client` gets you the whole stack already assembled. All of
them are in `tests/conftest.py`.

| Fixture | What it is |
|---|---|
| `mock_whisper_model` | A `WhisperModel` that always returns the same two French segments |
| `settings` | `Settings` forced to `DEVICE="cpu"`, so no test needs a GPU |
| `engine` | A `WhisperEngine` with that mock model already loaded |
| `db_session_maker` | A real in-memory SQLite, tables created, one shared connection |
| `auth_token` | A token genuinely minted through `create_token()`, returned in plain |
| `app_factory` | Builds the app with the mock engine, the test database and an `ADMIN_TOKEN` |
| `client` | An `AsyncClient` sending a valid Bearer token |
| `unauth_client` | The same with no `Authorization` header, for the 401 paths |

Two of those choices are worth knowing about.

**The database is real, not mocked.** It is SQLite in memory behind a `StaticPool`, so
every session in a test shares one connection and sees the same rows. Mocking it would
have meant asserting that the mock behaves like the mock, and the token code is exactly
where that would have hidden a bug.

**The model is the only thing faked.** `app_factory` patches
`rest.engine.WhisperModel` while building the app and then substitutes the prepared
engine, so the routing, the middleware, the auth dependency and the database are all
the real ones. What a test asserts about a response is what a client would receive.

```python
async def test_health_reports_the_device(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["device"] == "cpu"
```

## When a test fails

```bash
pytest -v tests/                                # which test, not just how many
pytest tests/test_engine.py::test_transcribe -v # one test, alone
pytest -l --pdb tests/                          # locals, then a debugger on the failure
```

An async test that passes suspiciously fast is the failure to suspect first: it means
`asyncio_mode` did not apply and the coroutine was never awaited, so nothing in it ran
and nothing in it could fail.
