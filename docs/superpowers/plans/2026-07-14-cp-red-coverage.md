# CP Red-Ball Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $superpower-subagents (recommended) or $superpower-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking via update_plan.

**Goal:** Evaluate and conditionally use a red-ball ranking model only when walk-forward holdout evidence exceeds both the current strategy and a deterministic random baseline.

**Architecture:** `backtest_ssq.py` supplies one red-only recency ranking that uses prior draws only. `backtest_production_plans.py` evaluates current, candidate, and deterministic-random pools with identical 8/9/10/11-red tiers and returns a conservative recommendation. `cp_prediction_core.py` persists the evaluation and selects the candidate version only after a qualifying stored evaluation.

**Tech Stack:** Python 3 standard library, SQLite, pytest.

---

### Task 1: Add a deterministic red-only candidate ranking

**Files:**
- Modify: `scripts/cp/backtest_ssq.py:930-965`
- Test: `tests/test_cp_prediction.py`

- [ ] **Step 1: Write a failing ranking test**

```python
def test_red_coverage_rank_uses_only_prior_draws(cp_core):
    history = [
        {"reds": [1, 2, 3, 4, 5, 6], "blue": 1, "red_sum": 21, "total_sum": 22},
        {"reds": [1, 2, 7, 8, 9, 10], "blue": 2, "red_sum": 37, "total_sum": 39},
    ]

    rank = backtest_ssq.rank_reds_for_coverage(history)

    assert rank[:2] == [1, 2]
    assert len(rank) == 33
    assert sorted(rank) == list(range(1, 34))
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `rtk python3 -m pytest tests/test_cp_prediction.py -k coverage_rank -q`

Expected: FAIL because `rank_reds_for_coverage` does not exist.

- [ ] **Step 3: Implement the minimal bounded ranking**

Add `rank_reds_for_coverage(history)` that scores all numbers with exponentially decayed historical appearances plus a bounded omission term and weak last-draw term. Sort by descending score, then number, and return all 33 distinct values.

- [ ] **Step 4: Run the test and verify it passes**

Run: `rtk python3 -m pytest tests/test_cp_prediction.py -k coverage_rank -q`

Expected: PASS.

### Task 2: Evaluate candidate, current, and random coverage without leakage

**Files:**
- Modify: `scripts/cp/backtest_production_plans.py:1-137`
- Test: `tests/test_cp_production_backtest.py`

- [ ] **Step 1: Write failing walk-forward and gate tests**

```python
def test_red_coverage_evaluation_keeps_holdout_draws_out_of_each_prediction():
    seen = []

    def ranker(history):
        seen.append([draw["issue_code"] for draw in history])
        return list(range(1, 34))

    result = evaluate_red_coverage(sample_draws(40), development_window=5, holdout_window=3, candidate_ranker=ranker)

    assert result["holdout"]["samples"] == 3
    assert seen[-3:] == [
        [f"2026{index:03d}" for index in range(1, 38)],
        [f"2026{index:03d}" for index in range(1, 39)],
        [f"2026{index:03d}" for index in range(1, 40)],
    ]


def test_red_coverage_gate_requires_beating_both_comparators():
    holdout = {
        "candidate": {"main": {"mean_red_hits": 2.0, "red5_plus_rate": 0.03}},
        "current": {"main": {"mean_red_hits": 1.9, "red5_plus_rate": 0.04}},
        "random": {"main": {"mean_red_hits": 1.8, "red5_plus_rate": 0.02}},
    }

    assert choose_red_coverage_recommendation(holdout) == "no_evidence"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `rtk python3 -m pytest tests/test_cp_production_backtest.py -k 'red_coverage' -q`

Expected: FAIL because the evaluator and gate do not exist.

- [ ] **Step 3: Implement the evaluator**

Create `evaluate_red_coverage` with `development_window=300` and `holdout_window=100`. For every evaluation index it builds pools from `draws[:index]` only, aggregates the four existing tiers, returns theoretical mean hits, and sets recommendation to `candidate` only if every tier exceeds current and random on both gate metrics.

- [ ] **Step 4: Run the test and verify it passes**

Run: `rtk python3 -m pytest tests/test_cp_production_backtest.py -k 'red_coverage' -q`

Expected: PASS.

### Task 3: Persist evidence and gate production strategy selection

**Files:**
- Modify: `scripts/cp/cp_prediction_core.py:20-85,276-405`
- Modify: `traeclaw/tasks/cp.py:45-58,178-205`
- Test: `tests/test_cp_prediction.py`

- [ ] **Step 1: Write failing persistence and fallback tests**

```python
def test_prediction_uses_current_strategy_without_qualifying_evaluation(cp_core):
    with sqlite3.connect(":memory:") as connection:
        cp_core.ensure_prediction_tables(connection)
        assert cp_core.resolve_prediction_strategy_version(connection) == "cp-v5.4"


def test_prediction_uses_candidate_only_after_qualifying_evaluation(cp_core):
    with sqlite3.connect(":memory:") as connection:
        cp_core.ensure_prediction_tables(connection)
        cp_core.record_red_coverage_evaluation(connection, {"recommendation": "candidate"})
        assert cp_core.resolve_prediction_strategy_version(connection) == "cp-v5.5-red-coverage"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `rtk python3 -m pytest tests/test_cp_prediction.py -k 'qualifying_evaluation or prediction_uses_current' -q`

Expected: FAIL because evaluation persistence and strategy resolution do not exist.

- [ ] **Step 3: Implement persistence and CLI evaluation**

Add `cp_red_coverage_evaluations` to the prediction schema, storing recommendation, evaluation JSON, and timestamp. Add `evaluate_red_coverage(conn)` to compute and persist results. Resolve `cp-v5.5-red-coverage` only from the latest `candidate` record; otherwise retain `cp-v5.4`. Add `python -m traeclaw.tasks.cp evaluate-red-coverage` to run the evaluation without creating a prediction plan.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `rtk python3 -m pytest tests/test_cp_prediction.py tests/test_cp_production_backtest.py -q`

Expected: PASS.

### Task 4: Verify with the real database and the full suite

**Files:**
- Modify: files above only

- [ ] **Step 1: Run the evaluator without changing a prediction**

Run: `rtk python3 -m traeclaw.tasks.cp evaluate-red-coverage`

Expected: JSON containing development/holdout metrics and `candidate`, `current`, or `no_evidence` recommendation.

- [ ] **Step 2: Run the full regression suite**

Run: `rtk python3 -m pytest tests -q`

Expected: PASS with zero failures.

- [ ] **Step 3: Review, commit, and push after the retry/overlap task is also complete**

Run: `rtk git diff --check && rtk git status --short`

Expected: no whitespace errors and no changes outside the scoped resilience and CP coverage work.
