from __future__ import annotations

import sys
from pathlib import Path

import pytest


CP_DIR = Path(__file__).resolve().parents[1] / "scripts" / "cp"
if str(CP_DIR) not in sys.path:
    sys.path.insert(0, str(CP_DIR))

import backtest_ssq  # noqa: E402
import cp_prediction_core  # noqa: E402


@pytest.fixture
def cp_core():
    return cp_prediction_core


def test_expand_reds_uses_candidate_rank(cp_core):
    base = [2, 10, 20, 25, 30, 31, 33]
    pool = [33, 31, 30, 25, 20, 10, 2, 29, 5, 17]

    assert cp_core.expand_reds(base, pool, 8) == [2, 10, 20, 25, 29, 30, 31, 33]


def test_four_plans_keep_single_blue_shapes_and_costs(cp_core):
    strategy = {
        "reds": [2, 10, 20, 25, 30, 31, 33],
        "blues": [8],
        "reason": {
            "target_sum": 96,
            "odd_target": 3,
            "ac_target": 7,
            "candidate_pool": [33, 31, 30, 25, 20, 10, 2, 29, 5, 17, 12],
            "blue_rank": [8, 3, 11],
        },
    }

    plans = cp_core.generate_main_and_reference(strategy)

    assert [
        (
            len(plan["tickets"][0]["reds"]),
            plan["tickets"][0]["blues"],
            plan["tickets"][0]["cost"],
        )
        for plan in plans
    ] == [
        (8, [8], 56),
        (9, [8], 168),
        (10, [8], 420),
        (11, [8], 924),
    ]


def test_production_strategy_version_is_v54(cp_core):
    assert cp_core.STRATEGY_VERSION == "cp-v5.4"


def test_v54_maps_to_single_blue_v52_base_selector(monkeypatch):
    calls = []

    def fake_pick(history, single_blue=False, candidate_mode="v3"):
        calls.append((history, single_blue, candidate_mode))
        return {"reds": [], "blues": []}

    monkeypatch.setattr(backtest_ssq, "pick_reds_v3", fake_pick)

    assert backtest_ssq.build_strategy([], "cp-v5.4") == {"reds": [], "blues": []}
    assert calls == [([], True, "v5.2")]
