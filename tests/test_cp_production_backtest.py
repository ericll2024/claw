from __future__ import annotations

import sys
import sqlite3
from pathlib import Path


CP_DIR = Path(__file__).resolve().parents[1] / "scripts" / "cp"
if str(CP_DIR) not in sys.path:
    sys.path.insert(0, str(CP_DIR))

from backtest_production_plans import (  # noqa: E402
    compare_expansions,
    connect_readonly,
    evaluate_plan,
)


def sample_strategy():
    return {
        "reds": [2, 10, 20, 25, 30, 31, 33],
        "blues": [8],
        "reason": {
            "candidate_pool": [33, 31, 30, 25, 20, 10, 2, 29, 5, 17, 12],
            "combo_count": 4,
        },
    }


def sample_draws(count):
    return [
        {
            "issue_code": f"2026{index:03d}",
            "draw_date": f"2026-01-{((index - 1) % 28) + 1:02d}",
            "reds": [1, 2, 3, 4, 5, 6],
            "blue": 16,
            "red_sum": 21,
            "total_sum": 37,
        }
        for index in range(1, count + 1)
    ]


def test_evaluate_plan_distinguishes_first_and_second_prize():
    draw = {"reds": [1, 2, 3, 4, 5, 6], "blue": 16}

    second = evaluate_plan([1, 2, 3, 4, 5, 6, 7, 8], [8], draw)
    first = evaluate_plan([1, 2, 3, 4, 5, 6, 7, 8], [16], draw)

    assert second == {
        "red_hits": 6,
        "blue_hit": False,
        "six_red_covered": True,
        "first_prize_hit": False,
        "second_prize_hit": True,
    }
    assert first["six_red_covered"] is True
    assert first["first_prize_hit"] is True
    assert first["second_prize_hit"] is False


def test_walk_forward_builder_only_receives_prior_draws():
    seen = []

    def builder(history, _version):
        seen.append([draw["issue_code"] for draw in history])
        return sample_strategy()

    result = compare_expansions(sample_draws(35), window=2, strategy_builder=builder)

    assert seen == [
        [f"2026{index:03d}" for index in range(1, 34)],
        [f"2026{index:03d}" for index in range(1, 35)],
    ]
    assert result["sample"] == 2
    assert result["range"] == ["2026034", "2026035"]


def test_comparison_reports_the_four_unchanged_purchase_tiers():
    result = compare_expansions(
        sample_draws(31),
        window=1,
        strategy_builder=lambda _history, _version: sample_strategy(),
    )

    expected = {
        "main": (8, 28, 56),
        "reference": (9, 84, 168),
        "budget_500": (10, 210, 420),
        "budget_1000": (11, 462, 924),
    }
    for mode in ("legacy", "ranked"):
        assert {
            plan_type: (
                metrics["red_count"],
                metrics["bet_count"],
                metrics["cost"],
            )
            for plan_type, metrics in result["modes"][mode].items()
        } == expected
        assert all(metrics["samples"] == 1 for metrics in result["modes"][mode].values())


def test_connect_readonly_opens_wal_snapshot_without_sidecars(tmp_path):
    db_file = tmp_path / "wal-snapshot.sqlite3"
    connection = sqlite3.connect(db_file)
    try:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE sample (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO sample VALUES (7)")
        connection.commit()
        assert connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{db_file}{suffix}")
        if sidecar.exists():
            sidecar.unlink()

    reader = connect_readonly(db_file)
    try:
        assert reader.execute("SELECT value FROM sample").fetchone() == (7,)
    finally:
        reader.close()
    
    import sys
    if sys.platform != "win32":
        assert not Path(f"{db_file}-wal").exists()
        assert not Path(f"{db_file}-shm").exists()


def test_connect_readonly_reads_committed_data_from_active_wal(tmp_path):
    db_file = tmp_path / "active-wal.sqlite3"
    writer = sqlite3.connect(db_file)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        writer.execute("CREATE TABLE sample (value INTEGER NOT NULL)")
        writer.execute("INSERT INTO sample VALUES (9)")
        writer.commit()
        assert Path(f"{db_file}-wal").exists()

        with connect_readonly(db_file) as reader:
            assert reader.execute("SELECT value FROM sample").fetchone() == (9,)
    finally:
        writer.close()
