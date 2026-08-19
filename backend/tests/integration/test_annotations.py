"""Integration tests for the annotations router."""

import pytest

from tests.helpers import seed_taiwan_directory

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture(autouse=True)
async def seed_directory(db):
    await seed_taiwan_directory(db, [{"symbol": "2331", "name": "測試股票一"}])


async def _create_asset(client):
    """Create a directory-backed Taiwan stock asset."""
    resp = await client.post("/api/assets", json={"symbol": "2331", "name": "測試股票一", "type": "stock"})
    assert resp.status_code == 201
    return resp.json()


class TestListAnnotations:
    async def test_empty_list(self, client):
        await _create_asset(client)
        resp = await client.get("/api/assets/2331/annotations")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_created_annotations(self, client):
        await _create_asset(client)
        await client.post("/api/assets/2331/annotations", json={
            "date": "2025-01-15", "title": "Earnings", "body": "Beat estimates",
        })
        resp = await client.get("/api/assets/2331/annotations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Earnings"

    async def test_404_for_unknown_asset(self, client):
        resp = await client.get("/api/assets/UNKNOWN/annotations")
        assert resp.status_code == 404


class TestCreateAnnotation:
    async def test_creates_annotation(self, client):
        await _create_asset(client)
        resp = await client.post("/api/assets/2331/annotations", json={
            "date": "2025-01-15", "title": "Earnings", "body": "Q1 beat",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Earnings"
        assert data["date"] == "2025-01-15"
        assert data["body"] == "Q1 beat"
        assert data["color"] == "#3b82f6"  # default

    async def test_custom_color(self, client):
        await _create_asset(client)
        resp = await client.post("/api/assets/2331/annotations", json={
            "date": "2025-01-15", "title": "Alert", "color": "#ff0000",
        })
        assert resp.status_code == 201
        assert resp.json()["color"] == "#ff0000"

    async def test_invalid_color_rejected(self, client):
        await _create_asset(client)
        resp = await client.post("/api/assets/2331/annotations", json={
            "date": "2025-01-15", "title": "Bad", "color": "red",
        })
        assert resp.status_code == 422

    async def test_404_for_unknown_asset(self, client):
        resp = await client.post("/api/assets/UNKNOWN/annotations", json={
            "date": "2025-01-15", "title": "Test",
        })
        assert resp.status_code == 404

    async def test_body_is_optional(self, client):
        await _create_asset(client)
        resp = await client.post("/api/assets/2331/annotations", json={
            "date": "2025-01-15", "title": "No body",
        })
        assert resp.status_code == 201
        assert resp.json()["body"] is None


class TestDeleteAnnotation:
    async def test_deletes_annotation(self, client):
        await _create_asset(client)
        create_resp = await client.post("/api/assets/2331/annotations", json={
            "date": "2025-01-15", "title": "To delete",
        })
        ann_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/assets/2331/annotations/{ann_id}")
        assert resp.status_code == 204

        # Verify it's gone
        list_resp = await client.get("/api/assets/2331/annotations")
        assert list_resp.json() == []

    async def test_404_for_nonexistent_annotation(self, client):
        await _create_asset(client)
        resp = await client.delete("/api/assets/2331/annotations/999")
        assert resp.status_code == 404

    async def test_404_for_unknown_asset(self, client):
        resp = await client.delete("/api/assets/UNKNOWN/annotations/1")
        assert resp.status_code == 404
