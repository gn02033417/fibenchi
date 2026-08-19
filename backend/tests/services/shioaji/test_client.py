"""Offline contract tests for the Shioaji sidecar HTTP boundary."""

from datetime import datetime, timezone

import httpx
import pytest

from app.config import Settings
from app.services.shioaji.client import (
    ShioajiClient,
    ShioajiHTTPError,
    ShioajiInfo,
    ShioajiTimeoutError,
    ShioajiUnavailableError,
)


def _client(handler, *, timeout: float = 1.0) -> ShioajiClient:
    return ShioajiClient(
        "http://shioaji-stub:8080",
        timeout=timeout,
        transport=httpx.MockTransport(handler),
    )


def test_settings_use_typed_sidecar_url_and_timeout():
    config = Settings(
        shioaji_base_url="http://shioaji-stub:8080",
        shioaji_timeout_seconds=2.5,
    )
    client = ShioajiClient(
        config.shioaji_base_url,
        timeout=config.shioaji_timeout_seconds,
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )

    assert str(config.shioaji_base_url) == "http://shioaji-stub:8080/"
    assert client.timeout.connect == 2.5


@pytest.mark.asyncio
async def test_health_info_and_stream_status_are_typed():
    async def handler(request: httpx.Request) -> httpx.Response:
        payloads = {
            "/api/v1/health": {"healthy": True, "simulation": True},
            "/api/v1/info": {
                "name": "Shioaji API Server",
                "version": "1.7.0",
                "protocols": ["HTTP/1.1"],
                "simulation": True,
            },
            "/api/v1/stream/status": {
                "active_connections": 2,
                "timestamp": "2026-08-19T12:00:00Z",
                "status": "healthy",
            },
        }
        return httpx.Response(200, json=payloads[request.url.path])

    client = _client(handler)

    health = await client.health()
    info = await client.info()
    stream = await client.stream_status()

    assert health.healthy is True
    assert info == ShioajiInfo(
        name="Shioaji API Server",
        version="1.7.0",
        protocols=["HTTP/1.1"],
        simulation=True,
    )
    assert stream.active_connections == 2
    assert stream.timestamp == datetime(2026, 8, 19, 12, tzinfo=timezone.utc)
    assert stream.status == "healthy"


@pytest.mark.asyncio
async def test_http_status_is_wrapped_with_typed_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "sidecar unavailable"})

    with pytest.raises(ShioajiHTTPError) as exc_info:
        await _client(handler).health()

    assert exc_info.value.status_code == 503
    assert exc_info.value.path == "/api/v1/health"


@pytest.mark.asyncio
async def test_timeout_is_wrapped_with_typed_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ShioajiTimeoutError):
        await _client(handler, timeout=0.01).health()


@pytest.mark.asyncio
async def test_connection_failure_is_wrapped_with_typed_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ShioajiUnavailableError):
        await _client(handler).health()
