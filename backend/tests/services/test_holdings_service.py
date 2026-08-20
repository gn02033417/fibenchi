"""Unit tests for the disabled ETF holdings seam."""

import pytest
from fastapi import HTTPException

from app.services.holdings_service import get_holdings, get_holdings_indicators

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def test_get_holdings_is_disabled():
    with pytest.raises(HTTPException) as exc_info:
        await get_holdings(None, "0051")

    assert exc_info.value.status_code == 410
    assert "Taiwan build" in exc_info.value.detail


async def test_get_holdings_indicators_is_disabled():
    with pytest.raises(HTTPException) as exc_info:
        await get_holdings_indicators(None, "0051")

    assert exc_info.value.status_code == 410
    assert "Taiwan build" in exc_info.value.detail
