"""Tests for the admin token-management API."""

import httpx
import pytest

_ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
async def admin_client(app_factory):
    app = app_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as c:
        yield c


async def test_create_token_requires_admin(admin_client):
    r = await admin_client.post("/admin/tokens", json={"name": "x"})
    assert r.status_code == 401


async def test_create_token_returns_plain_once(admin_client):
    r = await admin_client.post(
        "/admin/tokens", json={"name": "laptop"}, headers=_ADMIN
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "laptop"
    assert body["token"].startswith("sk_")


async def test_list_and_revoke_token(admin_client):
    created = (
        await admin_client.post("/admin/tokens", json={"name": "a"}, headers=_ADMIN)
    ).json()
    token_id = created["id"]

    listed = (await admin_client.get("/admin/tokens", headers=_ADMIN)).json()
    assert any(t["id"] == token_id for t in listed["tokens"])

    deleted = await admin_client.delete(f"/admin/tokens/{token_id}", headers=_ADMIN)
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True


async def test_token_stats_endpoint(admin_client):
    created = (
        await admin_client.post("/admin/tokens", json={"name": "s"}, headers=_ADMIN)
    ).json()
    r = await admin_client.get(f"/admin/tokens/{created['id']}/stats", headers=_ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["total_requests"] == 0
    assert body["token_name"] == "s"


async def test_dashboard_served(admin_client):
    r = await admin_client.get("/admin/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
