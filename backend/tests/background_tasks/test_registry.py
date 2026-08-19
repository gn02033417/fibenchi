"""Tests for the background-task registry and trigger resolution."""

from unittest.mock import patch

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.background_tasks import all_tasks
from app.background_tasks.jobs import _refresh_trigger
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
        assert isinstance(by_id["intraday_sync"].resolve_trigger(), IntervalTrigger)
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

        others = [t for t in all_tasks() if t.id != "price_refresh"]
        assert all(t.resolve_trigger() is not None for t in others)
