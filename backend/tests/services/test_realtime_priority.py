"""Pure tests for deterministic realtime subscription priority selection."""

import pytest

from app.config import Settings
from app.services.realtime_priority import compute_wanted_symbols


def test_compute_wanted_symbols_uses_the_documented_priority_order():
    wanted = compute_wanted_symbols(
        active_asset="0050",
        realtime_priority_groups=(("2330", "0050"), ("2317", "2330")),
        active_group_symbols=("1101", "2317"),
        recent_symbols=("2603", "1101"),
        tracked_symbols=("0050", "2330", "2317", "1101", "2603", "2303"),
        cap=10,
    )

    assert wanted == ["0050", "2330", "2317", "1101", "2603", "2303"]


def test_same_symbol_in_multiple_priority_sources_consumes_one_slot():
    wanted = compute_wanted_symbols(
        active_asset="0050",
        realtime_priority_groups=(("0050", "2330"), ("0050", "2317")),
        active_group_symbols=("0050", "1101"),
        recent_symbols=("0050", "2603"),
        tracked_symbols=("0050", "2330", "2317", "1101", "2603"),
        cap=5,
    )

    assert wanted == ["0050", "2330", "2317", "1101", "2603"]
    assert wanted.count("0050") == 1


def test_active_asset_cannot_be_evicted_by_lower_priority_symbols():
    wanted = compute_wanted_symbols(
        active_asset="0050",
        realtime_priority_groups=(("2330",),),
        active_group_symbols=("2317",),
        recent_symbols=("1101",),
        tracked_symbols=("2603",),
        cap=1,
    )

    assert wanted == ["0050"]


def test_tier_ties_are_sorted_and_cap_is_enforced_deterministically():
    first = compute_wanted_symbols(
        realtime_priority_groups=({"2317", "2330"},),
        active_group_symbols={"2603", "1101"},
        tracked_symbols={"0050", "2303", "1101"},
        cap=4,
    )
    second = compute_wanted_symbols(
        realtime_priority_groups=({"2317", "2330"},),
        active_group_symbols={"2603", "1101"},
        tracked_symbols={"0050", "2303", "1101"},
        cap=4,
    )

    assert first == second == ["2317", "2330", "1101", "2603"]
    assert len(first) == 4


def test_subscription_cap_is_configurable_and_must_be_positive():
    assert Settings(shioaji_max_subscriptions=7).shioaji_max_subscriptions == 7

    with pytest.raises(ValueError):
        compute_wanted_symbols(tracked_symbols=("0050",), cap=0)
