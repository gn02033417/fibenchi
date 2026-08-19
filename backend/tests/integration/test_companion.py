import json
import pathlib

import pytest

from tests.helpers import create_asset_via_api, seed_taiwan_directory

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture(autouse=True)
async def seed_directory(db):
    await seed_taiwan_directory(db, [
        {"symbol": "2331", "name": "測試股票一"},
        {"symbol": "2332", "name": "測試股票二"},
    ])


async def test_companion_config_shape(client):
    first = await create_asset_via_api(client, "2331", "測試股票一")
    await create_asset_via_api(client, "2332", "測試股票二")

    # A second (non-default) group containing only 2331 — exercises normalization
    # (2331 is in two groups but defined once in `tickers`).
    tech = (await client.post("/api/groups", json={"name": "Tech", "icon": "cpu"})).json()
    await client.post(f"/api/groups/{tech['id']}/assets", json={"asset_ids": [first["id"]]})

    # A tag on 2331.
    tag = (await client.post("/api/tags", json={"name": "tech", "color": "#3b82f6"})).json()
    await client.post(f"/api/assets/2331/tags/{tag['id']}")

    resp = await client.get("/api/companion/config")
    assert resp.status_code == 200
    body = resp.json()

    # Versioned + camelCase serialization for the TS consumer.
    assert body["version"] == 1
    assert "generatedAt" in body

    groups = {g["name"]: g for g in body["groups"]}
    assert groups["Watchlist"]["isDefault"] is True
    # Symbols are sorted deterministically (group_assets has no ordinal column).
    assert groups["Watchlist"]["symbols"] == ["2331", "2332"]
    assert groups["Tech"]["isDefault"] is False
    assert groups["Tech"]["symbols"] == ["2331"]

    # Ticker metadata defined once even though 2331 is in two groups.
    assert set(body["tickers"]) == {"2331", "2332"}
    first_ticker = body["tickers"]["2331"]
    assert first_ticker["name"] == "測試股票一"
    assert first_ticker["type"] == "stock"
    assert first_ticker["currency"] == "TWD"
    assert first_ticker["tags"] == ["tech"]

    assert body["tags"]["tech"] == "#3b82f6"


async def test_companion_config_empty_is_valid(client):
    # Only the seeded default Watchlist exists; bundle should still be well-formed.
    body = (await client.get("/api/companion/config")).json()
    assert body["version"] == 1
    assert isinstance(body["groups"], list)
    assert isinstance(body["tickers"], dict)
    assert isinstance(body["tags"], dict)


async def test_companion_schema_artifact_is_fresh():
    """The committed JSON Schema is the codegen input for the companion app, so it
    must stay in lock-step with the Pydantic SoT. If this fails, regenerate it:

        python -m scripts.export_companion_schema
    """
    from app.schemas.companion import CompanionConfig

    current = CompanionConfig.model_json_schema(by_alias=True)
    artifact = pathlib.Path(__file__).parents[2] / "companion.schema.json"
    on_disk = json.loads(artifact.read_text())
    assert current == on_disk, (
        "companion.schema.json is stale — run: python -m scripts.export_companion_schema"
    )
