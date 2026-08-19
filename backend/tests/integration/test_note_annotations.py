import pytest

from tests.helpers import create_asset_via_api, seed_taiwan_directory

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture(autouse=True)
async def seed_directory(db):
    await seed_taiwan_directory(db, [{"symbol": "2331", "name": "測試股票一"}])


async def test_get_empty_note(client):
    await create_asset_via_api(client, "2331", "測試股票一")
    resp = await client.get("/api/assets/2331/note")
    assert resp.status_code == 200
    assert resp.json()["content"] == ""


async def test_update_note(client):
    await create_asset_via_api(client, "2331", "測試股票一")
    resp = await client.put("/api/assets/2331/note", json={"content": "# Taiwan Note\n\nStrong ecosystem."})
    assert resp.status_code == 200
    assert "Taiwan Note" in resp.json()["content"]


async def test_update_note_twice(client):
    await create_asset_via_api(client, "2331", "測試股票一")
    await client.put("/api/assets/2331/note", json={"content": "v1"})
    resp = await client.put("/api/assets/2331/note", json={"content": "v2"})
    assert resp.json()["content"] == "v2"


async def test_note_nonexistent_asset(client):
    resp = await client.get("/api/assets/NOPE/note")
    assert resp.status_code == 404


async def test_create_annotation(client):
    await create_asset_via_api(client, "2331", "測試股票一")
    resp = await client.post("/api/assets/2331/annotations", json={
        "date": "2025-01-15",
        "title": "Earnings beat",
        "body": "Beat estimates by 10%",
        "color": "#22c55e",
    })
    assert resp.status_code == 201
    assert resp.json()["title"] == "Earnings beat"


async def test_list_annotations(client):
    await create_asset_via_api(client, "2331", "測試股票一")
    await client.post("/api/assets/2331/annotations", json={"date": "2025-01-10", "title": "Event A"})
    await client.post("/api/assets/2331/annotations", json={"date": "2025-01-20", "title": "Event B"})

    resp = await client.get("/api/assets/2331/annotations")
    assert len(resp.json()) == 2
    assert resp.json()[0]["title"] == "Event A"


async def test_delete_annotation(client):
    await create_asset_via_api(client, "2331", "測試股票一")
    resp = await client.post("/api/assets/2331/annotations", json={"date": "2025-01-15", "title": "Event"})
    aid = resp.json()["id"]

    resp = await client.delete(f"/api/assets/2331/annotations/{aid}")
    assert resp.status_code == 204

    resp = await client.get("/api/assets/2331/annotations")
    assert len(resp.json()) == 0


async def test_delete_nonexistent_annotation(client):
    await create_asset_via_api(client, "2331", "測試股票一")
    resp = await client.delete("/api/assets/2331/annotations/999")
    assert resp.status_code == 404
