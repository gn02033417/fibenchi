import pytest

from app.models.symbol_directory import SymbolDirectory

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture(autouse=True)
async def seed_taiwan_directory(db):
    db.add_all([
        SymbolDirectory(symbol="2330", name="台積電", exchange="TSE", type="stock", currency="TWD"),
        SymbolDirectory(symbol="0050", name="元大台灣50", exchange="TSE", type="etf", currency="TWD"),
        SymbolDirectory(symbol="6488", name="環球晶", exchange="OTC", type="stock", currency="TWD"),
        SymbolDirectory(symbol="2317", name="鴻海", exchange="TSE", type="stock", currency="TWD"),
        SymbolDirectory(symbol="2454", name="聯發科", exchange="TSE", type="stock", currency="TWD"),
        SymbolDirectory(symbol="2603", name="長榮", exchange="TSE", type="stock", currency="TWD"),
    ])
    await db.commit()


async def test_list_assets_empty(client):
    resp = await client.get("/api/assets")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_asset_with_name(client):
    resp = await client.post("/api/assets", json={
        "symbol": "2330",
        "name": "caller supplied name",
        "type": "etf",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "2330"
    assert data["name"] == "台積電"
    assert data["type"] == "stock"
    assert data["exchange"] == "TSE"
    assert data["currency"] == "TWD"


async def test_create_asset_auto_resolve(client):
    resp = await client.post("/api/assets", json={"symbol": "6488"})
    assert resp.status_code == 201
    assert resp.json()["symbol"] == "6488"
    assert resp.json()["name"] == "環球晶"
    assert resp.json()["exchange"] == "OTC"
    assert resp.json()["currency"] == "TWD"


async def test_create_asset_with_currency(client):
    resp = await client.post("/api/assets", json={"symbol": "0050"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "0050"
    assert data["exchange"] == "TSE"
    assert data["currency"] == "TWD"
    assert data["type"] == "etf"


async def test_create_asset_krw_currency(client):
    """Taiwan directory entries always create with TWD."""
    resp = await client.post("/api/assets", json={"symbol": "6488"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "6488"
    assert data["currency"] == "TWD"
    assert data["name"] == "環球晶"


async def test_create_asset_invalid_symbol(client):
    resp = await client.post("/api/assets", json={"symbol": "AAPL"})
    assert resp.status_code == 404
    assert "Taiwan symbol directory" in resp.json()["detail"]


async def test_create_duplicate_asset_returns_existing(client):
    """Creating an asset that already exists returns the existing record (idempotent)."""
    resp1 = await client.post("/api/assets", json={"symbol": "2330", "name": "台積電"})
    resp2 = await client.post("/api/assets", json={"symbol": "2330", "name": "台積電"})
    assert resp2.status_code == 201
    assert resp2.json()["id"] == resp1.json()["id"]


async def test_delete_asset(client):
    """``DELETE /api/assets/{symbol}`` is a soft-delete: the row is preserved
    so pseudo-ETF constituent relationships stay intact. The asset remains
    visible in the listing — only group membership is removed."""
    await client.post("/api/assets", json={"symbol": "2330", "name": "台積電"})
    resp = await client.delete("/api/assets/2330")
    assert resp.status_code == 204

    resp = await client.get("/api/assets")
    assert [a["symbol"] for a in resp.json()] == ["2330"]


async def test_delete_nonexistent_asset(client):
    resp = await client.delete("/api/assets/NOPE")
    assert resp.status_code == 404


async def test_asset_attachments_summary(client, db):
    """#536: the remove dialog reads this to warn before an orphan / hard delete."""
    from app.models import Asset, AssetType, Note
    from app.repositories.group_repo import GroupRepository

    asset = Asset(symbol="COFF.L", name="Coffee", type=AssetType.STOCK, currency="USD")
    db.add(asset)
    await db.flush()
    default_group = await GroupRepository(db).get_default()
    assert default_group is not None
    default_group.assets.append(asset)
    db.add(Note(asset_id=asset.id, content="hold through El Niño"))
    await db.commit()

    tid = (await client.post("/api/theses", json={"name": "El Niño"})).json()["id"]
    await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [asset.id]})

    body = (await client.get("/api/assets/COFF.L/attachments")).json()
    assert body["symbol"] == "COFF.L"
    assert body["groups"] == ["Watchlist"]
    assert body["theses"] == ["El Niño"]
    assert body["has_note"] is True
    assert body["annotation_count"] == 0
    assert body["pseudo_etfs"] == []


async def test_soft_delete_leaves_other_attachments(client, db):
    """Soft delete only detaches from the default group — thesis membership and the
    row survive (the exact orphan state #536 warns about)."""
    from app.models import Asset, AssetType
    from app.repositories.group_repo import GroupRepository

    asset = Asset(symbol="COFF.L", name="Coffee", type=AssetType.STOCK, currency="USD")
    db.add(asset)
    await db.flush()
    default_group = await GroupRepository(db).get_default()
    assert default_group is not None
    default_group.assets.append(asset)
    await db.commit()
    tid = (await client.post("/api/theses", json={"name": "El Niño"})).json()["id"]
    await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [asset.id]})

    assert (await client.delete("/api/assets/COFF.L")).status_code == 204

    # Row + thesis membership preserved; only the group link is gone.
    assert [a["symbol"] for a in (await client.get("/api/assets")).json()] == ["COFF.L"]
    assert {a["symbol"] for a in (await client.get(f"/api/theses/{tid}")).json()["assets"]} == {"COFF.L"}
    assert (await client.get("/api/assets/COFF.L/attachments")).json()["groups"] == []


async def test_hard_delete_cascades(client, db):
    """#536: hard delete removes the asset and every attachment — group / pseudo-ETF
    / thesis links, tag, note, annotation, prices, intraday bars — while the group /
    thesis / pseudo-ETF entities themselves survive. Relies on the DB ON DELETE
    CASCADE (tests enforce SQLite FK cascade, mirroring Postgres)."""
    from datetime import date, datetime, timezone

    from sqlalchemy import func, select

    from app.models import (
        Annotation,
        Asset,
        AssetType,
        IntradayPrice,
        Note,
        PriceHistory,
        PseudoETF,
        Tag,
        group_assets,
        pseudo_etf_constituents,
        tag_assets,
        thesis_assets,
    )
    from app.repositories.group_repo import GroupRepository
    from tests.conftest import TestSession

    asset = Asset(symbol="COFF.L", name="Coffee", type=AssetType.STOCK, currency="USD")
    db.add(asset)
    await db.flush()
    aid = asset.id

    default_group = await GroupRepository(db).get_default()
    assert default_group is not None
    default_group.assets.append(asset)
    tag = Tag(name="softs", color="#3b82f6")
    db.add(tag)
    petf = PseudoETF(name="Softs Basket", base_date=date(2026, 1, 1))
    petf.constituents.append(asset)
    db.add(petf)
    db.add(Note(asset_id=aid, content="thesis note"))
    db.add(Annotation(asset_id=aid, date=date(2026, 1, 1), title="entry"))
    db.add(PriceHistory(asset_id=aid, date=date(2026, 1, 1), open=1, high=1, low=1, close=1, volume=1))
    db.add(IntradayPrice(
        asset_id=aid, timestamp=datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc), price=1.0, volume=10,
    ))
    await db.commit()

    tid = (await client.post("/api/theses", json={"name": "El Niño"})).json()["id"]
    await client.post(f"/api/theses/{tid}/assets", json={"asset_ids": [aid]})

    assert (await client.delete("/api/assets/COFF.L?hard=true")).status_code == 204

    # Verify with a fresh session so we read the committed state cleanly.
    async with TestSession() as check:
        async def count(selectable, where):
            return (await check.execute(select(func.count()).select_from(selectable).where(where))).scalar_one()

        assert await count(Asset, Asset.id == aid) == 0
        for table in (group_assets, tag_assets, thesis_assets, pseudo_etf_constituents):
            assert await count(table, table.c.asset_id == aid) == 0
        for model in (Note, Annotation, PriceHistory, IntradayPrice):
            assert await count(model, model.asset_id == aid) == 0
        # Parent entities survive the cascade.
        assert await count(PseudoETF, PseudoETF.id == petf.id) == 1
        assert await count(Tag, Tag.id == tag.id) == 1
    assert (await client.get(f"/api/theses/{tid}")).status_code == 200


async def test_hard_delete_nonexistent_asset(client):
    assert (await client.delete("/api/assets/NOPE?hard=true")).status_code == 404


async def test_list_assets_returns_created(client):
    """``GET /api/assets`` returns every asset, ordered by symbol —
    including orphans not yet attached to any group."""
    await client.post("/api/assets", json={"symbol": "2330", "name": "台積電"})
    await client.post("/api/assets", json={"symbol": "6488", "name": "環球晶"})

    resp = await client.get("/api/assets")
    assert resp.status_code == 200
    symbols = [a["symbol"] for a in resp.json()]
    assert symbols == ["2330", "6488"]


async def test_list_assets_includes_orphans(client):
    """Regression for #507: a freshly POSTed asset must appear in GET /api/assets
    even before it has been attached to any group."""
    await client.post("/api/assets", json={"symbol": "2454", "name": "聯發科"})

    resp = await client.get("/api/assets")
    assert resp.status_code == 200
    symbols = [a["symbol"] for a in resp.json()]
    assert "2454" in symbols


# --- Taiwan directory metadata and provenance ---

async def test_directory_metadata_controls_type_and_currency(client):
    resp = await client.post("/api/assets", json={"symbol": "0050", "type": "stock"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "etf"
    assert data["exchange"] == "TSE"
    assert data["currency"] == "TWD"
    assert data["type_source"] == "auto"


async def test_directory_metadata_controls_otc_stock(client):
    resp = await client.post("/api/assets", json={"symbol": "6488"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "stock"
    assert data["exchange"] == "OTC"
    assert data["currency"] == "TWD"


async def test_suggestion_is_silent_when_it_agrees(client):
    resp = await client.post("/api/assets", json={"symbol": "2330"})
    assert resp.json()["suggested"]["disagrees"] == []


async def test_suggestion_flags_a_drifted_auto_row(client, db):
    """A row Fibenchi guessed wrong should offer itself up for correction."""
    from app.models import Asset, AssetType

    asset = Asset(
        symbol="^GSPC",
        name="S&P 500",
        type=AssetType.STOCK,
        currency="USD",
        unit_kind="CURRENCY",
    )
    db.add(asset)
    await db.commit()

    # Simulate the pre-migration state: auto-detected, and wrong.
    resp = await client.get("/api/assets")
    data = [a for a in resp.json() if a["symbol"] == "^GSPC"][0]
    assert set(data["suggested"]["disagrees"]) == {"type", "unit_kind"}
    assert data["suggested"]["type"] == "index"
    assert data["suggested"]["unit_kind"] == "points"
    # Advisory only — nothing was rewritten behind the user's back.
    assert data["type"] == "stock"


async def test_editing_a_field_silences_its_suggestion(client, db):
    """The whole point of provenance: once you decide, Fibenchi stops nagging —
    even though the shape still disagrees just as much."""
    from app.models import Asset, AssetType

    asset = Asset(
        symbol="^GSPC",
        name="S&P 500",
        type=AssetType.INDEX,
        currency="USD",
        unit_kind="POINTS",
    )
    db.add(asset)
    await db.commit()
    aid = asset.id
    asset.unit_kind = "CURRENCY"
    await db.commit()
    before = await client.get("/api/assets")
    assert "unit_kind" in [a for a in before.json() if a["id"] == aid][0]["suggested"]["disagrees"]

    resp = await client.patch(f"/api/assets/{aid}", json={"unit_kind": "currency"})
    assert resp.status_code == 200
    assert resp.json()["unit_source"] == "user"
    assert resp.json()["suggested"]["disagrees"] == []


async def test_patching_currency_also_claims_the_unit(client):
    """unit_kind and currency answer one question together, so taking over
    either means taking over both."""
    created = await client.post("/api/assets", json={"symbol": "2330"})

    resp = await client.patch(f"/api/assets/{created.json()['id']}", json={"currency": "EUR"})
    assert resp.json()["currency"] == "EUR"
    assert resp.json()["unit_source"] == "user"


async def test_user_set_field_stays_visible_and_resettable(client, db):
    """"Don't argue with you" must not collapse into "never speak again".

    A field the user set leaves `disagrees` (no nagging) but stays in
    `differs` — otherwise the recommendation vanishes the moment you touch the
    field, and the choice becomes one-way.
    """
    from app.models import Asset, AssetType

    asset = Asset(
        symbol="^N225",
        name="Nikkei 225",
        type=AssetType.INDEX,
        currency="JPY",
        unit_kind="POINTS",
    )
    db.add(asset)
    await db.commit()
    aid = asset.id

    resp = await client.patch(f"/api/assets/{aid}", json={"type": "etf", "unit_kind": "currency"})
    data = resp.json()
    assert data["type"] == "etf"
    assert data["suggested"]["disagrees"] == []          # quiet
    assert set(data["suggested"]["differs"]) == {"type", "unit_kind"}  # but visible


async def test_reset_detection_restores_auto(client, db):
    """The inverse of an edit: adopt the shape's answer and clear the flag, so
    the field tracks improvements again."""
    from app.models import Asset, AssetType

    asset = Asset(
        symbol="^N225",
        name="Nikkei 225",
        type=AssetType.INDEX,
        currency="JPY",
        unit_kind="POINTS",
    )
    db.add(asset)
    await db.commit()
    aid = asset.id
    await client.patch(f"/api/assets/{aid}", json={"type": "etf", "unit_kind": "currency"})

    resp = await client.post(f"/api/assets/{aid}/reset-detection", json={})
    data = resp.json()
    assert resp.status_code == 200
    assert data["type"] == "index"
    assert data["unit_kind"] == "points"
    assert data["type_source"] == "auto"
    assert data["unit_source"] == "auto"
    assert data["suggested"]["differs"] == []


async def test_reset_detection_is_per_field(client, db):
    from app.models import Asset, AssetType

    asset = Asset(
        symbol="^N225",
        name="Nikkei 225",
        type=AssetType.INDEX,
        currency="JPY",
        unit_kind="POINTS",
    )
    db.add(asset)
    await db.commit()
    aid = asset.id
    await client.patch(f"/api/assets/{aid}", json={"type": "etf", "unit_kind": "currency"})

    resp = await client.post(f"/api/assets/{aid}/reset-detection", json={"fields": ["unit_kind"]})
    data = resp.json()
    assert data["unit_kind"] == "points" and data["unit_source"] == "auto"
    assert data["type"] == "etf" and data["type_source"] == "user"


async def test_reset_detection_leaves_currency_alone(client):
    """Resetting detection does not overwrite a user-set currency."""
    created = await client.post("/api/assets", json={"symbol": "2330"})
    aid = created.json()["id"]
    await client.patch(f"/api/assets/{aid}", json={"currency": "EUR"})

    resp = await client.post(f"/api/assets/{aid}/reset-detection", json={})
    assert resp.json()["currency"] == "EUR"


async def test_reset_detection_unknown_asset_404(client):
    resp = await client.post("/api/assets/9999/reset-detection", json={})
    assert resp.status_code == 404
