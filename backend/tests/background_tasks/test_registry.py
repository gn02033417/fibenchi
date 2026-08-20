"""Tests for the background-task registry and trigger resolution."""

from unittest.mock import patch

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.background_tasks import all_tasks
from app.background_tasks.jobs import (
    _intraday_trigger,
    _refresh_trigger,
    scheduled_intraday_sync,
)
from app.background_tasks.registry import background_task

pytestmark = pytest.mark.asyncio(loop_scope="function")


class TestRegistry:
    async def test_all_expected_jobs_registered(self):
        ids = {t.id for t in all_tasks()}
        assert ids == {
            "price_refresh",
            "price_refresh_supplemental",
            "symbol_directory_sync",
            "taiwan_symbol_directory_sync",
            "intraday_sync",
            "price_heal",
        }

    async def test_duplicate_id_rejected(self):
        with pytest.raises(ValueError, match="price_heal"):
            @background_task("price_heal", trigger=IntervalTrigger(minutes=1))
            async def _clashing():
                pass

    async def test_static_triggers_resolve_to_themselves(self):
        by_id = {t.id: t for t in all_tasks()}
        assert by_id["intraday_sync"].resolve_trigger() is None
        assert isinstance(by_id["price_refresh_supplemental"].resolve_trigger(), CronTrigger)


class TestRefreshTrigger:
    async def test_valid_cron_builds_trigger(self):
        with patch("app.background_tasks.jobs.app_settings") as settings:
            settings.refresh_cron = "0 23 * * *"
            assert isinstance(_refresh_trigger(), CronTrigger)

    async def test_malformed_cron_disables_only_this_job(self, caplog):
        """A bad REFRESH_CRON must yield None (job skipped, loudly) — the other
        registered tasks keep their own triggers. Previously it silently
        disabled every background job."""
        with patch("app.background_tasks.jobs.app_settings") as settings:
            settings.refresh_cron = "not a cron"
            assert _refresh_trigger() is None
        assert any("REFRESH_CRON" in r.message for r in caplog.records)

        others = [t for t in all_tasks() if t.id not in {"price_refresh", "intraday_sync"}]
        assert all(t.resolve_trigger() is not None for t in others)


class TestIntradayTrigger:
    async def test_shioaji_mode_disables_legacy_yahoo_polling(self):
        with patch("app.background_tasks.jobs.app_settings") as settings:
            settings.price_provider = "shioaji"
            assert _intraday_trigger() is None

    async def test_non_taiwan_mode_keeps_legacy_trigger_available(self):
        with patch("app.background_tasks.jobs.app_settings") as settings:
            settings.price_provider = "yahoo"
            assert isinstance(_intraday_trigger(), IntervalTrigger)

    async def test_scheduled_job_is_a_noop_in_shioaji_mode(self):
        with (
            patch("app.background_tasks.jobs.app_settings") as settings,
            patch("app.background_tasks.jobs.fetch_and_store_intraday") as fetch,
        ):
            settings.price_provider = "shioaji"
            await scheduled_intraday_sync()

        fetch.assert_not_called()
