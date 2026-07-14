#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
from pathlib import Path
from urllib.parse import quote

from backtest_ssq import DB_PATH, build_strategy, load_draws, rank_reds_for_coverage
from cp_prediction_core import expand_reds, expand_reds_legacy


PLAN_RED_COUNTS = {
    "main": 8,
    "reference": 9,
    "budget_500": 10,
    "budget_1000": 11,
}
EXPANDERS = {
    "legacy": expand_reds_legacy,
    "ranked": expand_reds,
}


def evaluate_plan(reds, blues, draw):
    red_hits = len(set(reds) & set(draw["reds"]))
    blue_hit = draw["blue"] in blues
    six_red = red_hits == 6
    return {
        "red_hits": red_hits,
        "blue_hit": blue_hit,
        "six_red_covered": six_red,
        "first_prize_hit": six_red and blue_hit,
        "second_prize_hit": six_red and not blue_hit,
    }


def _new_metrics(red_count):
    bet_count = math.comb(red_count, 6)
    return {
        "red_count": red_count,
        "bet_count": bet_count,
        "cost": bet_count * 2,
        "samples": 0,
        "six_red_covered": 0,
        "first_prize_hits": 0,
        "second_prize_hits": 0,
        "red5_plus_hits": 0,
        "blue_hits": 0,
        "red_hits_total": 0,
    }


def _finalize_metrics(metrics):
    samples = metrics["samples"]
    result = dict(metrics)
    result["six_red_rate"] = round(metrics["six_red_covered"] / samples, 6)
    result["first_prize_rate"] = round(metrics["first_prize_hits"] / samples, 6)
    result["second_prize_rate"] = round(metrics["second_prize_hits"] / samples, 6)
    result["red5_plus_rate"] = round(metrics["red5_plus_hits"] / samples, 6)
    result["blue_hit_rate"] = round(metrics["blue_hits"] / samples, 6)
    result["mean_red_hits"] = round(metrics["red_hits_total"] / samples, 4)
    result["theoretical_mean_red_hits"] = round(6 * metrics["red_count"] / 33, 4)
    result["theoretical_six_red_probability"] = round(
        math.comb(metrics["red_count"], 6) / math.comb(33, 6),
        10,
    )
    result["theoretical_second_prize_probability"] = round(
        result["theoretical_six_red_probability"] * 15 / 16,
        10,
    )
    del result["red_hits_total"]
    return result


def _record_red_outcome(metrics, reds, draw):
    outcome = evaluate_plan(reds, [], draw)
    metrics["samples"] += 1
    metrics["red_hits_total"] += outcome["red_hits"]
    metrics["red5_plus_hits"] += int(outcome["red_hits"] >= 5)
    metrics["six_red_covered"] += int(outcome["six_red_covered"])


def deterministic_random_rank(issue_code):
    seed = int.from_bytes(hashlib.sha256(str(issue_code).encode("utf-8")).digest()[:8], "big")
    numbers = list(range(1, 34))
    random.Random(seed).shuffle(numbers)
    return numbers


def choose_red_coverage_recommendation(holdout_modes):
    candidate = holdout_modes.get("candidate", {})
    current = holdout_modes.get("current", {})
    random_mode = holdout_modes.get("random", {})
    if not candidate or set(candidate) != set(current) or set(candidate) != set(random_mode):
        return "no_evidence"

    for plan_type, candidate_metrics in candidate.items():
        current_metrics = current[plan_type]
        random_metrics = random_mode[plan_type]
        if not (
            candidate_metrics["mean_red_hits"] > current_metrics["mean_red_hits"]
            and candidate_metrics["mean_red_hits"] > random_metrics["mean_red_hits"]
            and candidate_metrics["red5_plus_rate"] > current_metrics["red5_plus_rate"]
            and candidate_metrics["red5_plus_rate"] > random_metrics["red5_plus_rate"]
        ):
            return "no_evidence"
    return "candidate"


def _new_red_metrics():
    return {plan_type: _new_metrics(red_count) for plan_type, red_count in PLAN_RED_COUNTS.items()}


def _finalize_red_metrics(metrics):
    return {plan_type: _finalize_metrics(values) for plan_type, values in metrics.items()}


def evaluate_red_coverage(
    draws,
    development_window=300,
    holdout_window=100,
    strategy_version="cp-v5.4",
    strategy_builder=build_strategy,
    candidate_ranker=rank_reds_for_coverage,
):
    if development_window <= 0 or holdout_window <= 0:
        raise ValueError("development and holdout windows must be greater than zero")
    start_index = max(30, len(draws) - development_window - holdout_window)
    if start_index >= len(draws) or len(draws) - start_index < holdout_window:
        raise ValueError("insufficient draws for red coverage evaluation")

    development = {mode: _new_red_metrics() for mode in ("current", "candidate", "random")}
    holdout = {mode: _new_red_metrics() for mode in ("current", "candidate", "random")}
    holdout_start = len(draws) - holdout_window

    for index in range(start_index, len(draws)):
        history = draws[:index]
        draw = draws[index]
        current_strategy = strategy_builder(history, strategy_version)
        current_base = list(current_strategy["reds"])
        current_pool = list((current_strategy.get("reason") or {}).get("candidate_pool") or current_base)
        candidate_rank = list(candidate_ranker(history))
        random_rank = deterministic_random_rank(draw["issue_code"])
        target = holdout if index >= holdout_start else development

        for plan_type, red_count in PLAN_RED_COUNTS.items():
            _record_red_outcome(target["current"][plan_type], expand_reds(current_base, current_pool, red_count), draw)
            _record_red_outcome(target["candidate"][plan_type], candidate_rank[:red_count], draw)
            _record_red_outcome(target["random"][plan_type], random_rank[:red_count], draw)

    finalized_development = {
        mode: _finalize_red_metrics(metrics)
        for mode, metrics in development.items()
    }
    finalized_holdout = {
        mode: _finalize_red_metrics(metrics)
        for mode, metrics in holdout.items()
    }
    return {
        "development": {"samples": len(draws) - holdout_window - start_index, "modes": finalized_development},
        "holdout": {"samples": holdout_window, "modes": finalized_holdout},
        "recommendation": choose_red_coverage_recommendation(finalized_holdout),
    }


def compare_expansions(
    draws,
    window=300,
    strategy_version="cp-v5.4",
    strategy_builder=build_strategy,
):
    if window <= 0:
        raise ValueError("window must be greater than zero")
    start_index = max(30, len(draws) - window)
    if start_index >= len(draws):
        raise ValueError("at least 31 draws are required for production backtesting")

    aggregates = {
        mode: {
            plan_type: _new_metrics(red_count)
            for plan_type, red_count in PLAN_RED_COUNTS.items()
        }
        for mode in EXPANDERS
    }
    fallback_periods = 0

    for index in range(start_index, len(draws)):
        history = draws[:index]
        draw = draws[index]
        strategy = strategy_builder(history, strategy_version)
        base_reds = list(strategy["reds"])
        blues = list(strategy["blues"][:1])
        if len(blues) != 1:
            raise ValueError("production comparison requires exactly one blue ball")
        reason = strategy.get("reason") or {}
        candidate_pool = list(reason.get("candidate_pool") or base_reds)
        if reason.get("combo_count") == 0:
            fallback_periods += 1

        for mode, expander in EXPANDERS.items():
            for plan_type, red_count in PLAN_RED_COUNTS.items():
                reds = expander(base_reds, candidate_pool, red_count)
                outcome = evaluate_plan(reds, blues, draw)
                metrics = aggregates[mode][plan_type]
                metrics["samples"] += 1
                metrics["red_hits_total"] += outcome["red_hits"]
                metrics["blue_hits"] += int(outcome["blue_hit"])
                metrics["red5_plus_hits"] += int(outcome["red_hits"] >= 5)
                metrics["six_red_covered"] += int(outcome["six_red_covered"])
                metrics["first_prize_hits"] += int(outcome["first_prize_hit"])
                metrics["second_prize_hits"] += int(outcome["second_prize_hit"])

    sample = len(draws) - start_index
    return {
        "strategy_version": strategy_version,
        "sample": sample,
        "range": [draws[start_index]["issue_code"], draws[-1]["issue_code"]],
        "fallback_periods": fallback_periods,
        "modes": {
            mode: {
                plan_type: _finalize_metrics(metrics)
                for plan_type, metrics in plan_metrics.items()
            }
            for mode, plan_metrics in aggregates.items()
        },
    }


def connect_readonly(db_path):
    resolved = Path(db_path).expanduser().resolve()
    base_uri = f"file:{quote(str(resolved))}?mode=ro"
    try:
        return _open_readonly_uri(base_uri)
    except sqlite3.OperationalError as exc:
        if "unable to open database file" not in str(exc).lower():
            raise
    return _open_readonly_uri(f"{base_uri}&immutable=1")


def _open_readonly_uri(uri):
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    except Exception:
        connection.close()
        raise
    return connection


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare legacy and rank-preserving expansion on production SSQ plans"
    )
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--window", type=int, default=300)
    parser.add_argument("--strategy-version", default="cp-v5.4")
    args = parser.parse_args(argv)

    with connect_readonly(args.db) as connection:
        draws = load_draws(connection)
    result = compare_expansions(
        draws,
        window=args.window,
        strategy_version=args.strategy_version,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
