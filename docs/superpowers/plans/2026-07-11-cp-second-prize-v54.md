# CP Second-Prize v5.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $superpower-subagents (recommended) or $superpower-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking via update_plan.

**Goal:** Keep the four existing 8/9/10/11-red single-blue purchase tiers while preserving model rank during expansion, measuring the actual production plans without future leakage, and fixing CP-path and high-prize settlement failures.

**Architecture:** The existing v5.2 base selector remains responsible for producing a seven-red core, ranked candidate pool, and one blue. The production layer expands that core without destroying candidate rank. A separate read-only walk-forward evaluator compares legacy and ranked expansion on the four real plan tiers and reports six-red coverage plus exact first/second-prize outcomes.

**Tech Stack:** Python 3, stdlib `sqlite3`/`itertools`/`argparse`, pytest, existing Traeclaw SQLite schema.

---

## File map

- Modify `scripts/cp/cp_prediction_core.py`: ranked and legacy expansion, strategy version, high-prize settlement, date-aware issue rollover.
- Modify `scripts/cp/backtest_ssq.py`: explicit `cp-v5.4` mapping.
- Create `scripts/cp/backtest_production_plans.py`: read-only production-tier walk-forward comparison.
- Modify `traeclaw/tasks/cp.py`: standalone project-root resolution and fetch failure handling.
- Create `tests/test_cp_prediction.py`: pure production-plan and settlement tests.
- Create `tests/test_cp_production_backtest.py`: evaluator metrics and no-future-data tests.
- Create `tests/test_cp_task_wrapper.py`: path and subprocess failure tests.

### Task 1: Preserve ranked expansion and retain a legacy comparator

**Files:**
- Create: `tests/test_cp_prediction.py`
- Modify: `scripts/cp/cp_prediction_core.py`
- Modify: `scripts/cp/backtest_ssq.py`

- [ ] **Step 1: Write failing rank and plan-shape tests**

```python
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
    assert [(len(p["tickets"][0]["reds"]), p["tickets"][0]["blues"], p["tickets"][0]["cost"]) for p in plans] == [
        (8, [8], 56), (9, [8], 168), (10, [8], 420), (11, [8], 924)
    ]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk python3 -m pytest tests/test_cp_prediction.py -q`

Expected: the rank test fails because current `expand_reds()` sorts `candidate_pool` numerically and selects `5` instead of ranked candidate `29`.

- [ ] **Step 3: Implement ranked expansion and version mapping**

```python
def expand_reds_legacy(base_reds, candidate_pool, target_count):
    return _expand_reds(base_reds, sorted(candidate_pool), target_count)


def expand_reds(base_reds, candidate_pool, target_count):
    return _expand_reds(base_reds, candidate_pool, target_count)


def _expand_reds(base_reds, candidate_pool, target_count):
    ranked_pool = list(dict.fromkeys(candidate_pool))
    reds = list(dict.fromkeys(base_reds))
    for number in ranked_pool:
        if number not in reds and len(reds) < target_count:
            reds.append(number)
    for number in range(1, 34):
        if number not in reds and len(reds) < target_count:
            reds.append(number)
    return sorted(reds[:target_count])
```

Set `STRATEGY_VERSION = "cp-v5.4"` and map `cp-v5.4` in `build_strategy()` to the same v5.2 base selector. Do not change the one-blue selector or tier sizes.

- [ ] **Step 4: Run focused and existing tests and verify GREEN**

Run: `rtk python3 -m pytest tests/test_cp_prediction.py tests/test_tasks.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
rtk git add scripts/cp/cp_prediction_core.py scripts/cp/backtest_ssq.py tests/test_cp_prediction.py
rtk git commit -m "feat(cp): preserve ranked candidates in plan expansion"
```

### Task 2: Add production-tier, leakage-safe evaluation

**Files:**
- Create: `scripts/cp/backtest_production_plans.py`
- Create: `tests/test_cp_production_backtest.py`

- [ ] **Step 1: Write failing metric and history-boundary tests**

```python
def test_evaluate_plan_distinguishes_first_and_second_prize():
    draw = {"reds": [1, 2, 3, 4, 5, 6], "blue": 16}
    second = evaluate_plan([1, 2, 3, 4, 5, 6, 7, 8], [8], draw)
    first = evaluate_plan([1, 2, 3, 4, 5, 6, 7, 8], [16], draw)
    assert second["six_red_covered"] is True
    assert second["second_prize_hit"] is True
    assert first["first_prize_hit"] is True


def test_walk_forward_builder_only_receives_prior_draws():
    seen = []
    def builder(history, _version):
        seen.append([d["issue_code"] for d in history])
        return sample_strategy()
    compare_expansions(sample_draws(35), window=2, strategy_builder=builder)
    assert seen == [[f"2026{i:03d}" for i in range(1, 34)], [f"2026{i:03d}" for i in range(1, 35)]]
```

- [ ] **Step 2: Run and verify RED**

Run: `rtk python3 -m pytest tests/test_cp_production_backtest.py -q`

Expected: import failure because `backtest_production_plans.py` does not exist.

- [ ] **Step 3: Implement the read-only evaluator**

The module must:

```python
PLAN_RED_COUNTS = {"main": 8, "reference": 9, "budget_500": 10, "budget_1000": 11}

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
```

`compare_expansions()` must iterate by absolute index over the unfiltered chronological draw list and pass only `draws[:index]` to the strategy builder. It must compare `legacy` and `ranked` expansion from the same base strategy, aggregate each plan tier, and never call `ensure_tables()` or write to SQLite. The CLI opens the DB with URI `mode=ro` and prints JSON.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `rtk python3 -m pytest tests/test_cp_production_backtest.py -q`

Expected: all tests pass.

- [ ] **Step 5: Run real multi-window comparisons**

Run:

```bash
rtk python3 scripts/cp/backtest_production_plans.py --db data/traeclaw.sqlite3 --window 300
rtk python3 scripts/cp/backtest_production_plans.py --db data/traeclaw.sqlite3 --window 1000
```

Record exact sample counts and tier metrics. Interpret six-red events as the primary target and red-five-plus/mean-red-hits only as sparse-event diagnostics, not proof of future predictive power.

- [ ] **Step 6: Commit**

```bash
rtk git add scripts/cp/backtest_production_plans.py tests/test_cp_production_backtest.py
rtk git commit -m "feat(cp): backtest production purchase tiers"
```

### Task 3: Correct high-prize settlement and issue rollover

**Files:**
- Modify: `tests/test_cp_prediction.py`
- Modify: `scripts/cp/cp_prediction_core.py`

- [ ] **Step 1: Add failing first/second-prize and rollover tests**

```python
def test_float_prize_is_recorded_when_amount_is_unknown(cp_core):
    draw = {"reds": [1, 2, 3, 4, 5, 6], "blue": 16}
    _, _, level, amount, breakdown = cp_core.single_ticket_return([1, 2, 3, 4, 5, 6], [8], draw)
    assert level == "二等奖x1"
    assert amount == 0
    assert breakdown == {"二等奖": 1}


def test_issue_rolls_over_using_next_draw_year(cp_core):
    assert cp_core.infer_next_issue("2025153", "2025-12-30") == "2026001"
```

- [ ] **Step 2: Run and verify RED**

Run: `rtk python3 -m pytest tests/test_cp_prediction.py -q`

Expected: high prize is currently reported as `未中奖`, and issue code becomes `2025154`.

- [ ] **Step 3: Implement minimal corrections**

- Count any `prize_level != "未中奖"` in `prize_counter`, while adding to `total_return` only when a fixed amount is known.
- Treat a non-empty prize breakdown as a winning ticket even if the floating payout is not yet known.
- Accept `last_draw_date` in `infer_next_issue()`, find the next Tuesday/Thursday/Sunday, and reset the sequence when that date enters a new year. Pass the latest draw date from `create_predictions()`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `rtk python3 -m pytest tests/test_cp_prediction.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
rtk git add scripts/cp/cp_prediction_core.py tests/test_cp_prediction.py
rtk git commit -m "fix(cp): retain floating high-prize outcomes"
```

### Task 4: Harden CP wrapper path and fetch failures

**Files:**
- Create: `tests/test_cp_task_wrapper.py`
- Modify: `traeclaw/tasks/cp.py`

- [ ] **Step 1: Write failing path and timeout tests**

```python
def test_default_project_root_is_standalone_repo(monkeypatch):
    monkeypatch.delenv("TRAECLAW_PROJECT_ROOT", raising=False)
    assert cp.project_root() == Path(__file__).resolve().parents[1]
    assert (cp.project_root() / "scripts" / "cp" / "fetch_ssq.py").is_file()


def test_fetch_timeout_returns_structured_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAECLAW_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(a[0], 180)))
    result = cp.fetch_latest()
    assert result["mode"] == "fetch_failed"
    assert result["error_type"] == "timeout"
```

- [ ] **Step 2: Run and verify RED**

Run: `rtk python3 -m pytest tests/test_cp_task_wrapper.py -q`

Expected: default root resolves one directory too high and timeout escapes the function.

- [ ] **Step 3: Implement path detection and failure handling**

- Default `project_root()` to the nearest parent containing both `scripts/cp` and `traeclaw`; preserve explicit `TRAECLAW_PROJECT_ROOT` compatibility, including an outer root that contains `code/`.
- Resolve the fetch script from the same scripts-directory helper used by `_load_cp_core()`.
- Catch `subprocess.TimeoutExpired` and `OSError`, returning `mode=fetch_failed`, a stable `error_type`, and user-readable `summary_text` without exposing secrets.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `rtk python3 -m pytest tests/test_cp_task_wrapper.py tests/test_tasks.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
rtk git add traeclaw/tasks/cp.py tests/test_cp_task_wrapper.py
rtk git commit -m "fix(cp): resolve standalone paths and fetch failures"
```

### Task 5: Review and full verification

**Files:**
- Review every changed file above.

- [ ] **Step 1: Run static syntax and whitespace checks**

Run:

```bash
rtk python3 -m compileall -q traeclaw scripts/cp tests
rtk git diff --check origin/main...HEAD
```

Expected: both exit 0 with no diagnostics.

- [ ] **Step 2: Run the complete suite**

Run: `rtk python3 -m pytest -q`

Expected: all tests pass with zero failures.

- [ ] **Step 3: Run read-only production smoke checks**

Run:

```bash
rtk python3 scripts/cp/backtest_production_plans.py --db data/traeclaw.sqlite3 --window 300
rtk python3 -c "from traeclaw.tasks import cp; print(cp.project_root()); print((cp.project_root() / 'scripts' / 'cp' / 'fetch_ssq.py').is_file())"
```

Expected: JSON contains both expansion modes and all four tiers; root is the standalone repository and fetch script existence is `True`.

- [ ] **Step 4: Request code review and fix Critical/Important findings**

Review the complete diff against this plan and design. Re-run focused tests after every fix.

- [ ] **Step 5: Final verification and integration**

Re-run the full suite after review fixes, then integrate the verified branch back into the user's current `main` worktree without discarding the pre-pull SQLite backup or stash.

## Verification summary

- Focused TDD proves each behavior failed before implementation and passed after the minimal change.
- Production backtest is read-only, reports the exact four purchase tiers, and never uses the target draw in its own history.
- Full pytest, compileall, diff check, code review, and current-DB smoke runs are required before completion.

**Next skill:** `$superpower-executing-plans`
