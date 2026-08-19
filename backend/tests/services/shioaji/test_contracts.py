"""Offline tests for the Shioaji STK contract adapter."""

import json
from pathlib import Path

import httpx
import pytest

from app.services.shioaji.client import (
    ShioajiClient,
    ShioajiContractsPage,
    ShioajiPayloadError,
)
from app.services.shioaji.contracts import (
    ShioajiContractSyncError,
    fetch_stk_contracts,
)

FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "shioaji" / "contracts.json"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, int | None, int | None]] = []

    async def list_contracts(self, security_type, *, page=None, page_size=None):
        self.calls.append((security_type, page, page_size))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return ShioajiContractsPage.model_validate(response)


def test_contract_fixture_contains_tse_otc_and_unsupported_types():
    payload = _fixture()["full"]

    assert {contract["exchange"] for contract in payload["contracts"]} >= {"TSE", "OTC", "TAIFEX"}
    assert {contract["security_type"] for contract in payload["contracts"]} >= {"STK", "FUT", "WRT"}


@pytest.mark.asyncio
async def test_full_stk_retrieval_filters_exchange_and_security_type_without_classifying_etf():
    client = FakeClient([_fixture()["full"]])

    results = await fetch_stk_contracts(client)

    assert [(item.exchange, item.code) for item in results] == [
        ("TSE", "2330"),
        ("OTC", "6488"),
        ("TSE", "0050"),
    ]
    assert client.calls == [("STK", None, None)]
    assert not hasattr(results[2], "type")


@pytest.mark.asyncio
async def test_paginated_stk_retrieval_uses_max_page_and_preserves_leading_zeroes():
    client = FakeClient(_fixture()["pages"])

    results = await fetch_stk_contracts(client, page_size=2)

    assert [(item.exchange, item.code) for item in results] == [
        ("TSE", "2330"),
        ("OTC", "6488"),
        ("TSE", "0050"),
    ]
    assert client.calls == [("STK", 1, 2), ("STK", 2, 2)]


@pytest.mark.asyncio
async def test_empty_upstream_is_typed_sync_failure():
    client = FakeClient([{"contracts": [], "security_type": "STK", "region": "TW"}])

    with pytest.raises(ShioajiContractSyncError, match="no usable"):
        await fetch_stk_contracts(client)


@pytest.mark.asyncio
async def test_malformed_upstream_is_typed_sync_failure():
    cause = ShioajiPayloadError("/api/v1/data/contracts", ValueError("missing code"))
    client = FakeClient([cause])

    with pytest.raises(ShioajiContractSyncError, match="contract retrieval failed") as exc_info:
        await fetch_stk_contracts(client)

    assert exc_info.value.__cause__ is cause


@pytest.mark.asyncio
async def test_client_uses_paginated_contract_endpoint_and_typed_payload():
    payload = _fixture()["pages"][0]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/data/contracts"
        assert dict(request.url.params) == {
            "security_type": "STK",
            "page": "1",
            "page_size": "2",
        }
        return httpx.Response(200, json=payload)

    client = ShioajiClient(
        "http://shioaji-stub:8080",
        transport=httpx.MockTransport(handler),
    )

    result = await client.list_contracts("STK", page=1, page_size=2)

    assert result.page == 1
    assert [contract.code for contract in result.contracts] == ["2330", "6488"]


@pytest.mark.asyncio
async def test_client_rejects_malformed_contract_record_as_typed_payload_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "contracts": [
                    {"security_type": "STK", "region": "TW", "exchange": "TSE"}
                ]
            },
        )

    client = ShioajiClient(
        "http://shioaji-stub:8080",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ShioajiPayloadError) as exc_info:
        await client.list_contracts()

    assert exc_info.value.path == "/api/v1/data/contracts"
