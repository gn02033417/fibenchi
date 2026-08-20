"""Tests for intraday price fetching and session classification."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.domain import AssetRef
from app.domain.phases import Session
from app.services.intraday import (
    _classify_session,
    persist_live_intraday_bars,
)
from app.services.intraday_aggregator import IntradayBucket
from app.services.yahoo import yahoo_client
from app.services.yahoo._intraday import ProviderIntradayBar
from app.services.yahoo.legacy_intraday import fetch_and_store_intraday

pytestmark = pytest.mark.asyncio(loop_scope="function")

ET = ZoneInfo("America/New_York")
CPH = ZoneInfo("Europe/Copenhagen")


# ---------- _classify_session ----------


class TestClassifySession:
    """Session classification: venue schedule first, wall-clock fallback."""

    async def test_us_premarket(self):
        ts = datetime(2026, 2, 25, 7, 0, tzinfo=ET)
        assert _classify_session(ts, AssetRef("AAPL")) == "pre"

    async def test_us_regular(self):
        ts = datetime(2026, 2, 25, 10, 0, tzinfo=ET)
        assert _classify_session(ts, AssetRef("AAPL")) == "regular"

    async def test_us_regular_at_open(self):
        ts = datetime(2026, 2, 25, 9, 30, tzinfo=ET)
        assert _classify_session(ts, AssetRef("AAPL")) == "regular"

    async def test_us_post_at_close(self):
        ts = datetime(2026, 2, 25, 16, 0, tzinfo=ET)
        assert _classify_session(ts, AssetRef("AAPL")) == "post"

    async def test_us_postmarket(self):
        ts = datetime(2026, 2, 25, 18, 0, tzinfo=ET)
        assert _classify_session(ts, AssetRef("AAPL")) == "post"

    async def test_us_half_day_post_after_early_close(self):
        """Day after Thanksgiving 2023: 13:00 ET close. 14:00 ET is post —
        the old wall-clock table filed it as regular."""
        ts = datetime(2023, 11, 24, 14, 0, tzinfo=ET)
        assert _classify_session(ts, AssetRef("AAPL")) == "post"

    async def test_copenhagen_regular(self):
        """NKT.CO: 10:00 CET is inside XCSE regular hours."""
        ts = datetime(2026, 2, 25, 10, 0, tzinfo=CPH)
        assert _classify_session(ts, AssetRef("NKT.CO")) == "regular"

    async def test_copenhagen_morning_auction_files_as_pre(self):
        """XCSE has no extended hours; an 8:30 bar is a closed-phase print
        filed to the nearer boundary — the upcoming open."""
        ts = datetime(2026, 2, 25, 8, 30, tzinfo=CPH)
        assert _classify_session(ts, AssetRef("NKT.CO")) == "pre"

    async def test_copenhagen_evening_files_as_post(self):
        ts = datetime(2026, 2, 25, 17, 30, tzinfo=CPH)
        assert _classify_session(ts, AssetRef("NKT.CO")) == "post"

    async def test_unknown_venue_uses_tz_fallback(self):
        """No venue but a bar timezone: generic local hours beat assuming ET."""
        ts = datetime(2026, 2, 25, 10, 0, tzinfo=CPH)
        assert _classify_session(ts, AssetRef("FOO.XX"), "Europe/Copenhagen") == "regular"

    async def test_unknown_venue_and_tz_falls_back_to_et(self):
        """Nothing to go on: 10:00 CET reads as 4:00 ET → 'pre'. Documents the
        residual fallback limitation for fully unresolvable symbols."""
        ts = datetime(2026, 2, 25, 10, 0, tzinfo=CPH)
        assert _classify_session(ts, AssetRef("FOO.XX"), None) == "pre"

    async def test_unknown_venue_bad_tz_string_falls_back_to_et(self):
        ts = datetime(2026, 2, 25, 10, 0, tzinfo=ET)
        assert _classify_session(ts, AssetRef("FOO.XX"), "Unknown/Timezone") == "regular"

    async def test_london_regular(self):
        ts = datetime(2026, 2, 25, 12, 0, tzinfo=ZoneInfo("Europe/London"))
        assert _classify_session(ts, AssetRef("HSBA.L")) == "regular"

    async def test_london_before_open_files_as_pre(self):
        ts = datetime(2026, 2, 25, 7, 30, tzinfo=ZoneInfo("Europe/London"))
        assert _classify_session(ts, AssetRef("HSBA.L")) == "pre"


# ---------- YahooClient.intraday ----------
#
# The Yahoo fetch lives on the client now. It returns divisor-normalised
# bars carrying ``tz_name`` so the intraday module can classify sessions.


def _make_hist_df(sym: str, timestamps: list[datetime], prices: list[float]) -> pd.DataFrame:
    """Build a DataFrame mimicking yahooquery multi-symbol history output."""
    data = {
        "close": prices,
        "open": prices,
        "high": prices,
        "low": prices,
        "volume": [1000] * len(prices),
    }
    idx = pd.DatetimeIndex(timestamps)
    mi = pd.MultiIndex.from_arrays(
        [[sym] * len(timestamps), idx],
        names=["symbol", "date"],
    )
    return pd.DataFrame(data, index=mi)


class TestClientIntraday:
    async def test_extracts_timezone_from_timestamps(self):
        """When Yahoo returns exchangeTimezoneName=None, tz is extracted from bar timestamps."""
        ts_list = [
            datetime(2026, 2, 25, 9, 0, tzinfo=CPH),
            datetime(2026, 2, 25, 10, 0, tzinfo=CPH),
            datetime(2026, 2, 25, 11, 0, tzinfo=CPH),
        ]
        hist = _make_hist_df("NKT.CO", ts_list, [100.0, 101.0, 102.0])

        price_data = {"NKT.CO": {
            "currency": "DKK",
            "exchangeTimezoneName": None,  # Yahoo returns None for Copenhagen
        }}

        mock_ticker = MagicMock()
        mock_ticker.price = price_data
        mock_ticker._get_data.return_value = {}
        mock_ticker._historical_data_to_dataframe.return_value = hist

        with patch("app.services.yahoo.client.Ticker", return_value=mock_ticker):
            result = await yahoo_client.intraday(["NKT.CO"])

        assert "NKT.CO" in result
        # Each bar carries tz_name so the caller can classify sessions later.
        tz_names = {bar.tz_name for bar in result["NKT.CO"]}
        assert all(tz and "Copenhagen" in tz for tz in tz_names)

    async def test_calls_get_data_with_include_prepost(self):
        """Verify the Yahoo API call includes includePrePost=true."""
        hist = _make_hist_df("KTOS", [], [])

        mock_ticker = MagicMock()
        mock_ticker.price = {}
        mock_ticker._get_data.return_value = {}
        mock_ticker._historical_data_to_dataframe.return_value = hist

        with patch("app.services.yahoo.client.Ticker", return_value=mock_ticker):
            await yahoo_client.intraday(["KTOS"])

        mock_ticker._get_data.assert_called_once_with(
            "chart",
            {"range": "1d", "interval": "1m", "includePrePost": "true"},
        )

    async def test_empty_symbols_returns_empty(self):
        assert await yahoo_client.intraday([]) == {}

    async def test_omitted_symbol_is_padded_not_keyerror(self):
        """#593: a symbol absent from Yahoo's chart response is padded with an
        empty payload before frame-building, so one omission can't abort the
        whole batch (staging 2026-08-05: KeyError '2914.T' killed a full
        82-symbol intraday sync)."""
        ts_list = [datetime(2026, 2, 25, 15, 0, tzinfo=timezone.utc)]
        hist = _make_hist_df("AAPL", ts_list, [100.0])

        mock_ticker = MagicMock()
        mock_ticker.price = {"AAPL": {"currency": "USD",
                                      "exchangeTimezoneName": "America/New_York"}}
        # Raw chart response contains AAPL but omits 2914.T entirely.
        mock_ticker._get_data.return_value = {"AAPL": {"timestamp": [1]}}
        mock_ticker._historical_data_to_dataframe.return_value = hist

        with patch("app.services.yahoo.client.Ticker", return_value=mock_ticker):
            result = await yahoo_client.intraday(["AAPL", "2914.T"])

        assert "AAPL" in result
        assert "2914.T" not in result
        padded = mock_ticker._historical_data_to_dataframe.call_args[0][0]
        assert padded["2914.T"] == {}

    async def test_applies_currency_divisor(self):
        """Subunit currencies (e.g. GBp) should divide prices."""
        ts_list = [datetime(2026, 2, 25, 10, 0, tzinfo=ZoneInfo("Europe/London"))]
        hist = _make_hist_df("VOD.L", ts_list, [8500.0])

        price_data = {"VOD.L": {
            "currency": "GBp",
            "exchangeTimezoneName": "Europe/London",
        }}

        mock_ticker = MagicMock()
        mock_ticker.price = price_data
        mock_ticker._get_data.return_value = {}
        mock_ticker._historical_data_to_dataframe.return_value = hist

        with patch("app.services.yahoo.client.Ticker", return_value=mock_ticker):
            with patch("app.services.yahoo._intraday.resolve_currency", return_value=("GBP", 100)):
                result = await yahoo_client.intraday(["VOD.L"])

        assert result["VOD.L"][0].price == 85.0

    async def test_filters_synthetic_non_minute_boundary_bars(self):
        """Yahoo echo bars at non-minute-boundary timestamps are dropped."""
        ts_list = [
            datetime(2026, 2, 25, 10, 0, 0, tzinfo=CPH),    # real: on minute
            datetime(2026, 2, 25, 10, 3, 43, tzinfo=CPH),   # synthetic: 43s offset
            datetime(2026, 2, 25, 10, 5, 0, tzinfo=CPH),    # real: on minute
        ]
        hist = _make_hist_df("P911.DE", ts_list, [41.0, 41.75, 42.0])

        price_data = {"P911.DE": {
            "currency": "EUR",
            "exchangeTimezoneName": "Europe/Berlin",
        }}

        mock_ticker = MagicMock()
        mock_ticker.price = price_data
        mock_ticker._get_data.return_value = {}
        mock_ticker._historical_data_to_dataframe.return_value = hist

        with patch("app.services.yahoo.client.Ticker", return_value=mock_ticker):
            result = await yahoo_client.intraday(["P911.DE"])

        assert "P911.DE" in result
        assert len(result["P911.DE"]) == 2  # synthetic bar dropped
        prices = [bar.price for bar in result["P911.DE"]]
        assert prices == [41.0, 42.0]

    async def test_skips_symbol_on_key_error(self):
        """Symbols missing from the DataFrame are silently skipped."""
        hist = _make_hist_df("AAPL", [datetime(2026, 2, 25, 10, 0, tzinfo=ET)], [180.0])

        mock_ticker = MagicMock()
        mock_ticker.price = {"AAPL": {"currency": "USD", "exchangeTimezoneName": "America/New_York"}}
        mock_ticker._get_data.return_value = {}
        mock_ticker._historical_data_to_dataframe.return_value = hist

        with patch("app.services.yahoo.client.Ticker", return_value=mock_ticker):
            result = await yahoo_client.intraday(["AAPL", "MISSING"])

        assert "AAPL" in result
        assert "MISSING" not in result


# ---------- fetch_and_store_intraday ----------
#
# This integration adds session classification (which depends on
# per-exchange trading hours) on top of the client's raw bars.


class TestFetchAndStoreIntraday:
    """Tests for DB storage: stale-bar cleanup and upsert."""

    async def test_deletes_stale_bars_before_upsert(self):
        """Bars older than the oldest fresh bar should be deleted."""
        fresh_bars = [
            ProviderIntradayBar(timestamp=datetime(2026, 2, 25, 9, 0, tzinfo=ET), price=30.0, volume=100, tz_name="America/New_York"),
            ProviderIntradayBar(timestamp=datetime(2026, 2, 25, 10, 0, tzinfo=ET), price=31.0, volume=200, tz_name="America/New_York"),
        ]

        mock_db = AsyncMock()

        with patch.object(yahoo_client, "intraday", new_callable=AsyncMock, return_value={"KTOS": fresh_bars}):
            count = await fetch_and_store_intraday(mock_db, [AssetRef("KTOS", 1)])

        assert count == 2

        # Should have 2 execute calls: 1 delete + 1 upsert
        calls = mock_db.execute.call_args_list
        assert len(calls) == 2

        # First call is the delete for stale bars
        delete_sql = str(calls[0].args[0])
        assert "DELETE" in delete_sql.upper()

    async def test_no_data_returns_zero(self):
        mock_db = AsyncMock()

        with patch.object(yahoo_client, "intraday", new_callable=AsyncMock, return_value={}):
            count = await fetch_and_store_intraday(mock_db, [AssetRef("KTOS", 1)])

        assert count == 0
        mock_db.execute.assert_not_called()

    async def test_skips_refs_without_stored_id(self):
        """Bars for refs not bound to a stored asset row are skipped."""
        fresh_bars = [
            ProviderIntradayBar(timestamp=datetime(2026, 2, 25, 9, 0, tzinfo=ET), price=30.0, volume=100, tz_name="America/New_York"),
        ]
        mock_db = AsyncMock()

        with patch.object(yahoo_client, "intraday", new_callable=AsyncMock, return_value={"UNKNOWN": fresh_bars}):
            count = await fetch_and_store_intraday(mock_db, [AssetRef("UNKNOWN")])

        assert count == 0


class TestPersistLiveIntradayBars:
    async def test_persists_completed_buckets_using_existing_intraday_key(self):
        mock_db = AsyncMock()
        bar = IntradayBucket(
            symbol="2330",
            timestamp=datetime(2026, 8, 20, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            open=100,
            high=103,
            low=99,
            close=102,
            volume=12,
            session=Session.REGULAR,
            status="completed",
        )

        count = await persist_live_intraday_bars(mock_db, [AssetRef("2330", 1)], [bar])

        assert count == 1
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()
        assert "ON CONFLICT" in str(mock_db.execute.await_args.args[0]).upper()

    async def test_does_not_persist_forming_bucket(self):
        mock_db = AsyncMock()
        bar = IntradayBucket(
            symbol="2330",
            timestamp=datetime(2026, 8, 20, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            open=100,
            high=100,
            low=100,
            close=100,
            volume=1,
            session=Session.REGULAR,
            status="forming",
        )

        count = await persist_live_intraday_bars(mock_db, [AssetRef("2330", 1)], [bar])

        assert count == 0
        mock_db.execute.assert_not_awaited()
        mock_db.commit.assert_not_awaited()
