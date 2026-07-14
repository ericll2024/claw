from __future__ import annotations

import sys
import json
import sqlite3
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


def test_red_coverage_rank_uses_only_prior_draws():
    history = [
        {"reds": [1, 2, 3, 4, 5, 6], "blue": 1, "red_sum": 21, "total_sum": 22},
        {"reds": [1, 2, 7, 8, 9, 10], "blue": 2, "red_sum": 37, "total_sum": 39},
    ]

    rank = backtest_ssq.rank_reds_for_coverage(history)

    assert rank[:2] == [1, 2]
    assert len(rank) == 33
    assert sorted(rank) == list(range(1, 34))


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


def test_prediction_uses_current_strategy_without_qualifying_evaluation(cp_core):
    with sqlite3.connect(":memory:") as connection:
        cp_core.ensure_prediction_tables(connection)

        assert cp_core.resolve_prediction_strategy_version(connection) == "cp-v5.4"


def test_prediction_uses_candidate_only_after_qualifying_evaluation(cp_core):
    with sqlite3.connect(":memory:") as connection:
        cp_core.ensure_prediction_tables(connection)
        cp_core.record_red_coverage_evaluation(connection, {"recommendation": "candidate"})

        assert cp_core.resolve_prediction_strategy_version(connection) == "cp-v5.5-red-coverage"


def test_v54_maps_to_single_blue_v52_base_selector(monkeypatch):
    calls = []

    def fake_pick(history, single_blue=False, candidate_mode="v3"):
        calls.append((history, single_blue, candidate_mode))
        return {"reds": [], "blues": []}

    monkeypatch.setattr(backtest_ssq, "pick_reds_v3", fake_pick)

    assert backtest_ssq.build_strategy([], "cp-v5.4") == {"reds": [], "blues": []}
    assert calls == [([], True, "v5.2")]


def test_float_second_prize_is_recorded_when_amount_is_unknown(cp_core):
    draw = {"reds": [1, 2, 3, 4, 5, 6], "blue": 16}

    hit_red, hit_blue, level, amount, breakdown = cp_core.single_ticket_return(
        [1, 2, 3, 4, 5, 6],
        [8],
        draw,
    )

    assert (hit_red, hit_blue) == (6, False)
    assert level == "二等奖x1"
    assert amount == 0
    assert breakdown == {"二等奖": 1}


def test_float_first_prize_is_recorded_when_amount_is_unknown(cp_core):
    draw = {"reds": [1, 2, 3, 4, 5, 6], "blue": 16}

    _, _, level, amount, breakdown = cp_core.single_ticket_return(
        [1, 2, 3, 4, 5, 6],
        [16],
        draw,
    )

    assert level == "一等奖x1"
    assert amount == 0
    assert breakdown == {"一等奖": 1}


def test_settlement_counts_floating_prize_as_winning_ticket(cp_core):
    with sqlite3.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE ssq_draws (
              issue_code TEXT PRIMARY KEY,
              draw_date TEXT NOT NULL,
              red1 INTEGER NOT NULL,
              red2 INTEGER NOT NULL,
              red3 INTEGER NOT NULL,
              red4 INTEGER NOT NULL,
              red5 INTEGER NOT NULL,
              red6 INTEGER NOT NULL,
              blue INTEGER NOT NULL,
              red_sum INTEGER NOT NULL,
              total_sum INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO ssq_draws VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026001", "2026-01-01", 1, 2, 3, 4, 5, 6, 16, 21, 37),
        )
        cp_core.ensure_prediction_tables(connection)
        now = cp_core.now_iso()
        summary = {
            "label": "主推 8+1",
            "ticket_count": 1,
            "sample_reds": ["01,02,03,04,05,06"],
            "blues": "08",
            "bet_count": 1,
            "cost": 2,
        }
        cursor = connection.execute(
            """
            INSERT INTO cp_prediction_plans (
              issue_code, strategy_version, plan_type, bet_type, budget,
              ticket_count, bet_count, cost, blues, summary_json, reason_json,
              status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026001",
                "cp-v5.4",
                "main",
                "6红+1蓝复式",
                2,
                1,
                1,
                2,
                "08",
                json.dumps(summary, ensure_ascii=False),
                json.dumps({"logic": "test"}),
                "predicted",
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO cp_prediction_tickets (
              plan_id, ticket_no, label, reds, blues, bet_count, cost, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, 1, "test", "01,02,03,04,05,06", "08", 1, 2, now),
        )

        result = cp_core.settle_issue(connection, "2026001")

    settlement = result["plans"][0]["result"]
    assert settlement["winning_tickets"] == 1
    assert settlement["total_bonus"] == 0
    assert settlement["ticket_results"][0]["breakdown"] == {"二等奖": 1}


def test_issue_rolls_over_using_next_draw_year(cp_core):
    assert cp_core.infer_next_issue("2025153", "2025-12-30") == "2026001"


def test_issue_increments_when_next_draw_stays_in_same_year(cp_core):
    assert cp_core.infer_next_issue("2025152", "2025-12-28") == "2025153"
