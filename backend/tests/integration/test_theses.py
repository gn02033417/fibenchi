"""Integration tests for the global thesis API — CRUD + membership."""

from datetime import date

import pytest

from app.models import Asset, AssetType, PriceHistory
from tests.helpers import create_asset_via_api, seed_taiwan_directory

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture(autouse=True)
async def _seed_directory(db):
    await seed_taiwan_directory(db, [
        {"symbol": "2331", "name": "測試股票一"},
        {"symbol": "2332", "name": "測試股票二"},
    ])


async def _seed_asset_with_closes(db, symbol: str, closes: dict[date, float]) -> Asset:
    asset = Asset(symbol=symbol, name=symbol, type=AssetType.STOCK, currency="USD")
    db.add(asset)
    await db.flush()
    for d, c in closes.items():
        db.add(PriceHistory(asset_id=asset.id, date=d, open=c, high=c, low=c, close=c, volume=1000))
    await db.commit()
    return asset


async def test_create_and_list_thesis(client):
    resp = await client.post("/api/theses", json={
        "name": "El Niño", "description": "advisories", "status": "live", "opened_at": "2026-03-01",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "El Niño"
    assert body["status"] == "live"
    assert body["opened_at"] == "2026-03-01"
    assert body["color"] == "#3b82f6"
    assert body["assets"] == []

    listing = await client.get("/api/theses")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


async def test_create_defaults(client):
    resp = await client.post("/api/theses", json={"name": "Cables"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "watching"      # default lifecycle
    assert body["opened_at"]                 # defaulted to today
    assert body["color"] == "#3b82f6"        # default colour


async def test_duplicate_name_rejected(client):
    await client.post("/api/theses", json={"name": "Dupe"})
    resp = await client.post("/api/theses", json={"name": "Dupe"})
    assert resp.status_code == 400


async def test_invalid_color_rejected(client):
    resp = await client.post("/api/theses", json={"name": "BadColor", "color": "red"})
    assert resp.status_code == 422


async def test_invalid_status_rejected(client):
    resp = await client.post("/api/theses", json={"name": "BadStatus", "status": "bananas"})
    assert resp.status_code == 422


async def test_update_thesis(client):
    tid = (await client.post("/api/theses", json={"name": "Orig"})).json()["id"]
    resp = await client.put(f"/api/theses/{tid}", json={
        "name": "Renamed", "status": "played_out", "color": "#ff0000",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["status"] == "played_out"
    assert body["color"] == "#ff0000"


async def test_update_to_duplicate_name_rejected(client):
    await client.post("/api/theses", json={"name": "Alpha"})
    bid = (await client.post("/api/theses", json={"name": "Beta"})).json()["id"]
    # renaming Beta -> Alpha collides
    resp = await client.put(f"/api/theses/{bid}", json={"name": "Alpha"})
    assert resp.status_code == 400
    # renaming to its own name is fine (no-op collision check)
    assert (await client.put(f"/api/theses/{bid}", json={"name": "Beta"})).status_code == 200


async def test_add_nonexistent_asset_rejected(client):
    coco = await create_asset_via_api(client, "2331", "測試股票一")
    tid = (await client.post("/api/theses", json={"name": "El Niño"})).json()["id"]
    resp = await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [coco["id"], 999999]})
    assert resp.status_code == 404
    # the valid id must not have been partially added
    assert (await client.get(f"/api/theses/{tid}")).json()["assets"] == []


async def test_delete_thesis(client):
    tid = (await client.post("/api/theses", json={"name": "ToDelete"})).json()["id"]
    assert (await client.delete(f"/api/theses/{tid}")).status_code == 204
    assert (await client.get(f"/api/theses/{tid}")).status_code == 404


async def test_get_nonexistent_404(client):
    assert (await client.get("/api/theses/9999")).status_code == 404
    assert (await client.delete("/api/theses/9999/assets/1")).status_code == 404


async def test_add_and_remove_members(client):
    coco = await create_asset_via_api(client, "2331", "測試股票一")
    ecaf = await create_asset_via_api(client, "2332", "測試股票二")
    tid = (await client.post("/api/theses", json={"name": "El Niño"})).json()["id"]

    resp = await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [coco["id"], ecaf["id"]]})
    assert resp.status_code == 200
    assert {a["symbol"] for a in resp.json()["assets"]} == {"2331", "2332"}

    # idempotent re-add does not duplicate
    resp = await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [coco["id"]]})
    assert len(resp.json()["assets"]) == 2

    # remove one
    resp = await client.delete(f"/api/theses/{tid}/assets/{coco['id']}")
    assert resp.status_code == 200
    assert {a["symbol"] for a in resp.json()["assets"]} == {"2332"}


async def test_members_returned_as_full_assets(client, db):
    """#533: members come back as full asset rows (type/currency/tags), even when
    the asset is in no group — so the theses page renders every member instead of
    dropping groupless ones while still counting them in the aggregate."""
    # Seed directly (NOT via the API), so the asset belongs to zero groups — the
    # exact orphan state that used to vanish from the theses table.
    orphan = await _seed_asset_with_closes(db, "ORPH.L", {date(2026, 3, 1): 100.0})
    tid = (await client.post("/api/theses", json={"name": "Orphans"})).json()["id"]

    resp = await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [orphan.id]})
    assert resp.status_code == 200
    members = resp.json()["assets"]
    assert len(members) == 1
    member = members[0]
    assert member["symbol"] == "ORPH.L"
    # Full AssetResponse shape, not the old id/symbol/name brief.
    assert member["type"] == "stock"
    assert member["currency"] == "USD"
    assert member["tags"] == []


async def test_asset_in_multiple_theses(client):
    coco = await create_asset_via_api(client, "2331", "測試股票一")
    t1 = (await client.post("/api/theses", json={"name": "El Niño"})).json()["id"]
    t2 = (await client.post("/api/theses", json={"name": "Softs"})).json()["id"]

    await client.post(f"/api/theses/{t1}/assets", json={"asset_ids": [coco["id"]]})
    await client.post(f"/api/theses/{t2}/assets", json={"asset_ids": [coco["id"]]})

    for tid in (t1, t2):
        body = (await client.get(f"/api/theses/{tid}")).json()
        assert any(a["symbol"] == "2331" for a in body["assets"])


async def test_aggregate_pct_null_without_members(client):
    body = (await client.post("/api/theses", json={"name": "Empty"})).json()
    assert body["aggregate_pct"] is None


async def test_aggregate_pct_equal_weight_since_opened_at(db, client):
    # A: open 100 -> latest 120 (+20%)
    a = await _seed_asset_with_closes(db, "AAA", {date(2026, 3, 1): 100.0, date(2026, 3, 15): 120.0})
    # B: a PRE-open price (50 on Jan 1) that must be ignored; open 100 -> latest 110 (+10%)
    b = await _seed_asset_with_closes(
        db, "BBB", {date(2026, 1, 1): 50.0, date(2026, 3, 1): 100.0, date(2026, 3, 20): 110.0}
    )

    tid = (await client.post("/api/theses", json={"name": "Agg", "opened_at": "2026-03-01"})).json()["id"]
    resp = await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [a.id, b.id]})

    # aggregate is on the membership response and the detail/list responses
    assert resp.json()["aggregate_pct"] == 15.0  # mean(+20%, +10%); B anchored to its Mar 1 close
    assert (await client.get(f"/api/theses/{tid}")).json()["aggregate_pct"] == 15.0
    listed = next(t for t in (await client.get("/api/theses")).json() if t["id"] == tid)
    assert listed["aggregate_pct"] == 15.0


async def test_performance_endpoint_curve(db, client):
    a = await _seed_asset_with_closes(db, "PPA", {date(2026, 3, 1): 100.0, date(2026, 3, 15): 120.0})
    b = await _seed_asset_with_closes(db, "PPB", {date(2026, 3, 1): 100.0, date(2026, 3, 20): 110.0})
    tid = (await client.post("/api/theses", json={"name": "Perf", "opened_at": "2026-03-01"})).json()["id"]
    await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [a.id, b.id]})

    resp = await client.get("/api/theses/performance")
    assert resp.status_code == 200  # also proves /performance isn't captured by /{thesis_id}
    pts = next(s for s in resp.json() if s["thesis_id"] == tid)["points"]
    assert pts, "expected a non-empty curve"
    assert [p["date"] for p in pts] == sorted(p["date"] for p in pts)  # ascending
    assert pts[0] == {"date": "2026-03-01", "pct": 0.0}                # open anchor
    assert pts[-1]["pct"] == 15.0                                      # matches aggregate_pct


async def test_performance_endpoint_empty_thesis(client):
    tid = (await client.post("/api/theses", json={"name": "Hollow"})).json()["id"]
    resp = await client.get("/api/theses/performance")
    assert resp.status_code == 200
    assert next(s for s in resp.json() if s["thesis_id"] == tid)["points"] == []
