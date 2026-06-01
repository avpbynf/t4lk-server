"""Test that authenticated requests write UsageLog rows."""

from sqlalchemy import func, select

from rest.db.models import UsageLog

_WAV = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00"
    b"\x02\x00\x10\x00data\x00\x00\x00\x00"
)


async def test_authenticated_request_writes_usage_log(client, db_session_maker):
    await client.post(
        "/v1/audio/transcriptions", files={"file": ("t.wav", _WAV, "audio/wav")}
    )

    async with db_session_maker() as s:
        count = (
            await s.execute(select(func.count()).select_from(UsageLog))
        ).scalar_one()
        row = (await s.execute(select(UsageLog))).scalars().first()

    assert count == 1
    assert row.endpoint == "/v1/audio/transcriptions"
    assert row.process_time is not None


async def test_public_health_writes_no_usage_log(client, db_session_maker):
    await client.get("/health")
    async with db_session_maker() as s:
        count = (
            await s.execute(select(func.count()).select_from(UsageLog))
        ).scalar_one()
    assert count == 0
