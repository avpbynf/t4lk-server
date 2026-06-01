"""Integration tests for Bearer token auth on /v1 routes."""

import httpx

_WAV = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00"
    b"\x02\x00\x10\x00data\x00\x00\x00\x00"
)


def _audio():
    return {"file": ("t.wav", _WAV, "audio/wav")}


async def test_health_is_public(unauth_client):
    assert (await unauth_client.get("/health")).status_code == 200


async def test_transcription_without_token_returns_401(unauth_client):
    r = await unauth_client.post("/v1/audio/transcriptions", files=_audio())
    assert r.status_code == 401


async def test_transcription_with_bad_token_returns_401(app_factory):
    app = app_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": "Bearer sk_invalid"},
    ) as c:
        r = await c.post("/v1/audio/transcriptions", files=_audio())
    assert r.status_code == 401


async def test_transcription_with_valid_token_returns_200(client):
    r = await client.post("/v1/audio/transcriptions", files=_audio())
    assert r.status_code == 200
