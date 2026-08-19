import pytest

from tests.helpers import create_asset_via_api, seed_taiwan_directory

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture(autouse=True)
async def _seed_directory(db):
    await seed_taiwan_directory(db, [
        {"symbol": "2331", "name": "測試股票一"},
        {"symbol": "2332", "name": "測試股票二"},
    ])


@pytest.fixture(autouse=True)
def _disable_historical_sync(monkeypatch):
    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.pseudo_etf_service.sync_asset_prices", _noop)


async def test_create_pseudo_etf(client):
    resp = await client.post("/api/pseudo-etfs", json={
        "name": "Quantum",
        "description": "Quantum computing stocks",
        "base_date": "2025-01-01",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Quantum"
    assert data["base_value"] == 100.0
    assert data["constituents"] == []


async def test_list_pseudo_etfs(client):
    await client.post("/api/pseudo-etfs", json={"name": "A", "base_date": "2025-01-01"})
    await client.post("/api/pseudo-etfs", json={"name": "B", "base_date": "2025-01-01"})

    resp = await client.get("/api/pseudo-etfs")
    assert len(resp.json()) == 2


async def test_get_pseudo_etf(client):
    resp = await client.post("/api/pseudo-etfs", json={"name": "Test", "base_date": "2025-01-01"})
    etf_id = resp.json()["id"]

    resp = await client.get(f"/api/pseudo-etfs/{etf_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test"


async def test_update_pseudo_etf(client):
    resp = await client.post("/api/pseudo-etfs", json={"name": "Old", "base_date": "2025-01-01"})
    etf_id = resp.json()["id"]

    resp = await client.put(f"/api/pseudo-etfs/{etf_id}", json={"name": "New", "description": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"
    assert resp.json()["description"] == "Updated"


async def test_delete_pseudo_etf(client):
    resp = await client.post("/api/pseudo-etfs", json={"name": "Del", "base_date": "2025-01-01"})
    etf_id = resp.json()["id"]

    resp = await client.delete(f"/api/pseudo-etfs/{etf_id}")
    assert resp.status_code == 204


async def test_add_constituents(client):
    a1 = await create_asset_via_api(client, "2331", "測試股票一")
    a2 = await create_asset_via_api(client, "2332", "測試股票二")

    resp = await client.post("/api/pseudo-etfs", json={"name": "Quantum", "base_date": "2025-01-01"})
    etf_id = resp.json()["id"]

    resp = await client.post(f"/api/pseudo-etfs/{etf_id}/constituents", json={
        "asset_ids": [a1["id"], a2["id"]]
    })
    assert resp.status_code == 200
    assert len(resp.json()["constituents"]) == 2


async def test_remove_constituent(client):
    a1 = await create_asset_via_api(client, "2331", "測試股票一")
    a2 = await create_asset_via_api(client, "2332", "測試股票二")

    resp = await client.post("/api/pseudo-etfs", json={"name": "Quantum", "base_date": "2025-01-01"})
    etf_id = resp.json()["id"]

    await client.post(f"/api/pseudo-etfs/{etf_id}/constituents", json={
        "asset_ids": [a1["id"], a2["id"]]
    })

    resp = await client.delete(f"/api/pseudo-etfs/{etf_id}/constituents/{a1['id']}")
    assert resp.status_code == 200
    assert len(resp.json()["constituents"]) == 1
    assert resp.json()["constituents"][0]["symbol"] == "2332"


async def test_duplicate_name(client):
    await client.post("/api/pseudo-etfs", json={"name": "Same", "base_date": "2025-01-01"})
    resp = await client.post("/api/pseudo-etfs", json={"name": "Same", "base_date": "2025-01-01"})
    assert resp.status_code == 400


async def test_performance_empty(client):
    resp = await client.post("/api/pseudo-etfs", json={"name": "Empty", "base_date": "2025-01-01"})
    etf_id = resp.json()["id"]

    resp = await client.get(f"/api/pseudo-etfs/{etf_id}/performance")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_nonexistent(client):
    resp = await client.get("/api/pseudo-etfs/999")
    assert resp.status_code == 404
