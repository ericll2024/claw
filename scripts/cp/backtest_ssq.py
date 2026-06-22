#!/usr/bin/env python3
import argparse
import itertools
import json
import math
import sqlite3
import statistics
import uuid
from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
_data_db = _current_dir.parents[1] / "data" / "traeclaw.sqlite3"
_state_db = _current_dir.parents[1] / "state" / "cp" / "doublecolor.db"
if _data_db.exists():
    _default_db = _data_db
else:
    _default_db = _state_db

DB_PATH = os.environ.get("CP_DB_PATH", str(_default_db.resolve()))

CREATE_SQL = '''
CREATE TABLE IF NOT EXISTS backtest_runs (
  run_id TEXT PRIMARY KEY,
  strategy_version TEXT NOT NULL,
  start_issue TEXT NOT NULL,
  end_issue TEXT NOT NULL,
  issue_count INTEGER NOT NULL,
  total_budget INTEGER NOT NULL,
  total_return INTEGER NOT NULL,
  second_prize_hits INTEGER NOT NULL,
  notes_json TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backtest_details (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  issue_code TEXT NOT NULL,
  draw_date TEXT NOT NULL,
  history_count INTEGER NOT NULL,
  bet_type TEXT NOT NULL,
  red_candidates TEXT NOT NULL,
  blue_candidates TEXT NOT NULL,
  chosen_numbers_json TEXT NOT NULL,
  bet_count INTEGER NOT NULL,
  cost INTEGER NOT NULL,
  hit_red INTEGER NOT NULL,
  hit_blue INTEGER NOT NULL,
  prize_level TEXT NOT NULL,
  return_amount INTEGER NOT NULL,
  review_note TEXT,
  next_adjustment TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, issue_code)
);
CREATE INDEX IF NOT EXISTS idx_backtest_details_run_issue ON backtest_details(run_id, issue_code);
'''

PRIZE_MAP = {
    (6, True): ('一等奖', 0),
    (6, False): ('二等奖', 0),
    (5, True): ('三等奖', 3000),
    (5, False): ('四等奖', 200),
    (4, True): ('四等奖', 200),
    (4, False): ('五等奖', 10),
    (3, True): ('五等奖', 10),
    (2, True): ('六等奖', 5),
    (1, True): ('六等奖', 5),
    (0, True): ('六等奖', 5),
}


def ensure_tables(conn):
    conn.executescript(CREATE_SQL)
    conn.commit()


def parse_row(row):
    return {
        'issue_code': row[0],
        'draw_date': row[1],
        'reds': list(row[2:8]),
        'blue': row[8],
        'red_sum': row[9],
        'total_sum': row[10],
    }


def load_draws(conn):
    cur = conn.execute('''
      SELECT issue_code, draw_date, red1, red2, red3, red4, red5, red6, blue, red_sum, total_sum
      FROM ssq_draws ORDER BY issue_code ASC
    ''')
    return [parse_row(r) for r in cur.fetchall()]


def median_or_default(values, default):
    return int(round(statistics.median(values))) if values else default


def is_prime(n):
    if n < 2:
        return False
    for i in range(2, int(math.sqrt(n)) + 1):
        if n % i == 0:
            return False
    return True


def ac_value(nums):
    nums = sorted(nums)
    diffs = set()
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            diffs.add(nums[j] - nums[i])
    return len(diffs) - (len(nums) - 1)


def zone_counts(nums):
    return [sum(1 for x in nums if 1 <= x <= 11), sum(1 for x in nums if 12 <= x <= 22), sum(1 for x in nums if 23 <= x <= 33)]


def tail_count(nums):
    tails = Counter(x % 10 for x in nums)
    return max(tails.values()) if tails else 0


def same_tail_group_count(nums):
    tails = Counter(x % 10 for x in nums)
    return sum(1 for v in tails.values() if v >= 2)


def consecutive_groups(nums):
    nums = sorted(nums)
    groups = 0
    active = False
    for i in range(1, len(nums)):
        if nums[i] == nums[i - 1] + 1:
            if not active:
                groups += 1
                active = True
        else:
            active = False
    return groups


def quality_metrics(draws):
    sums = [d['red_sum'] for d in draws]
    odd_counts = [sum(1 for x in d['reds'] if x % 2 == 1) for d in draws]
    big_counts = [sum(1 for x in d['reds'] if x > 16) for d in draws]
    prime_counts = [sum(1 for x in d['reds'] if is_prime(x)) for d in draws]
    ac_counts = [ac_value(d['reds']) for d in draws]
    zone_patterns = [zone_counts(d['reds']) for d in draws]
    return {
        'target_sum': median_or_default(sums, 96),
        'odd_target': median_or_default(odd_counts, 3),
        'big_target': median_or_default(big_counts, 3),
        'prime_target': median_or_default(prime_counts, 2),
        'ac_target': median_or_default(ac_counts, 7),
        'zone_target': [median_or_default([z[i] for z in zone_patterns], 2) for i in range(3)],
    }


def build_frequency_windows(history):
    last10 = history[-10:]
    last30 = history[-30:]
    last50 = history[-50:]
    last100 = history[-100:]
    hot10 = Counter()
    hot30 = Counter()
    hot100 = Counter()
    for draw in last10:
        hot10.update(draw['reds'])
    for draw in last30:
        hot30.update(draw['reds'])
    for draw in last100:
        hot100.update(draw['reds'])
    cold50 = Counter({n: 0 for n in range(1, 34)})
    omission = {}
    for n in range(1, 34):
        cold50[n] = 50 - sum(1 for draw in last50 if n in draw['reds'])
        gap = 0
        for draw in reversed(last50):
            if n in draw['reds']:
                break
            gap += 1
        omission[n] = gap
    blue10 = Counter(draw['blue'] for draw in last10)
    blue30 = Counter(draw['blue'] for draw in last30)
    return hot10, hot30, hot100, cold50, omission, blue10, blue30


def build_pair_counts(history, limit=100):
    recent = history[-limit:]
    pair_counts = Counter()
    for draw in recent:
        for pair in itertools.combinations(sorted(draw['reds']), 2):
            pair_counts[pair] += 1
    return pair_counts


def similarity_score(draw_a, draw_b):
    set_a = set(draw_a['reds']) if isinstance(draw_a, dict) else set(draw_a)
    set_b = set(draw_b['reds']) if isinstance(draw_b, dict) else set(draw_b)
    overlap = len(set_a & set_b)
    zone_a = zone_counts(sorted(set_a))
    zone_b = zone_counts(sorted(set_b))
    odd_a = sum(1 for x in set_a if x % 2 == 1)
    odd_b = sum(1 for x in set_b if x % 2 == 1)
    sum_a = sum(set_a)
    sum_b = sum(set_b)
    return overlap * 2.0 - abs(odd_a - odd_b) * 0.45 - abs(sum_a - sum_b) * 0.03 - sum(abs(zone_a[i] - zone_b[i]) * 0.3 for i in range(3))


def build_target_profile(history, lookback=160, top_k=24):
    recent = history[-lookback:]
    if len(recent) < 20:
        return {'sample_draws': [], 'single_counts': Counter(), 'pair_counts': Counter(), 'triple_counts': Counter()}
    scored = []
    for idx in range(8, len(recent)):
        anchor = recent[idx]
        prev = recent[max(0, idx - 8):idx]
        sim = sum(similarity_score(anchor, d) for d in prev) / max(len(prev), 1)
        scored.append((sim, anchor))
    scored.sort(reverse=True, key=lambda x: x[0])
    sample_draws = [draw for _, draw in scored[:top_k]]
    single_counts = Counter()
    pair_counts = Counter()
    triple_counts = Counter()
    for draw in sample_draws:
        reds = sorted(draw['reds'])
        single_counts.update(reds)
        for pair in itertools.combinations(reds, 2):
            pair_counts[pair] += 1
        for triple in itertools.combinations(reds, 3):
            triple_counts[triple] += 1
    return {
        'sample_draws': sample_draws,
        'single_counts': single_counts,
        'pair_counts': pair_counts,
        'triple_counts': triple_counts,
    }


def score_red_v1(n, hot_counter, cold_counter, last_draw, target_sum, odd_target, prime_target):
    score = 0.0
    score += hot_counter.get(n, 0) * 1.7
    score += cold_counter.get(n, 0) * 0.6
    if n in last_draw:
        score -= 1.8
    if n % 2 == odd_target % 2:
        score += 0.15
    if is_prime(n):
        score += 0.2 if prime_target >= 2 else -0.1
    mid = target_sum / 6
    score -= abs(n - mid) * 0.03
    if 12 <= n <= 24:
        score += 0.25
    return score


def score_red_v2(n, hot10, hot30, cold50, omission, last_draw, metrics):
    score = 0.0
    score += hot10.get(n, 0) * 1.2
    score += hot30.get(n, 0) * 0.8
    score += min(cold50.get(n, 0), 18) * 0.12
    score += min(omission.get(n, 0), 12) * 0.18
    if n in last_draw:
        score -= 1.2
    if 12 <= n <= 22:
        score += 0.35
    if is_prime(n):
        score += 0.25
    if n % 2 == 1:
        score += 0.08 if metrics['odd_target'] >= 3 else -0.02
    if n > 16:
        score += 0.08 if metrics['big_target'] >= 3 else -0.02
    score -= abs(n - (metrics['target_sum'] / 6)) * 0.028
    return score


def score_red_v3(n, hot10, hot30, cold50, omission, last_draw, metrics):
    score = 0.0
    score += hot10.get(n, 0) * 1.15
    score += hot30.get(n, 0) * 0.78
    omission_score = min(omission.get(n, 0), 10)
    cold_score = min(cold50.get(n, 0), 18)
    if 4 <= omission_score <= 8:
        score += 0.95
    elif omission_score >= 9:
        score += 0.35
    elif omission_score <= 1:
        score -= 0.7
    score += cold_score * 0.06
    if n in last_draw:
        score -= 0.95
    if 12 <= n <= 22:
        score += 0.75
    elif 9 <= n <= 24:
        score += 0.28
    else:
        score -= 0.12
    if is_prime(n):
        score += 0.16 if metrics['prime_target'] >= 2 else 0.01
    if n % 2 == 1 and metrics['odd_target'] >= 3:
        score += 0.08
    if n > 16 and metrics['big_target'] >= 3:
        score += 0.08
    score -= abs(n - (metrics['target_sum'] / 6)) * 0.02
    return score


def score_red_v33(n, hot10, hot30, hot100, cold50, omission, last_draw, metrics):
    score = 0.0
    score += hot10.get(n, 0) * 0.95
    score += hot30.get(n, 0) * 0.8
    score += hot100.get(n, 0) * 0.32
    omission_score = min(omission.get(n, 0), 12)
    if 3 <= omission_score <= 8:
        score += 0.9
    elif omission_score >= 9:
        score += 0.18
    elif omission_score <= 1:
        score -= 0.75
    score += min(cold50.get(n, 0), 16) * 0.045
    if n in last_draw:
        score -= 0.85
    if 12 <= n <= 22:
        score += 0.95
    elif 9 <= n <= 24:
        score += 0.22
    else:
        score -= 0.18
    if is_prime(n):
        score += 0.14 if metrics['prime_target'] >= 2 else 0.02
    if n % 2 == 1 and metrics['odd_target'] >= 3:
        score += 0.06
    if n > 16 and metrics['big_target'] >= 3:
        score += 0.05
    score -= abs(n - (metrics['target_sum'] / 6)) * 0.018
    return score


def score_red_v4(n, hot10, hot30, hot100, cold50, omission, last_draw, metrics, target_profile):
    score = score_red_v33(n, hot10, hot30, hot100, cold50, omission, last_draw, metrics)
    sample_draws = target_profile.get('sample_draws', [])
    if sample_draws:
        appear_count = sum(1 for draw in sample_draws if n in draw['reds'])
        score += appear_count * 0.22
    if 13 <= n <= 21:
        score += 0.18
    return score


def compute_regime(history, window=12):
    recent = history[-window:]
    if len(recent) < max(8, window // 2):
        return 'neutral', {'sum_cv': 0.0, 'zone_dom': 0.0, 'ac_cv': 0.0}
    sums = [d['red_sum'] for d in recent]
    acs = [ac_value(d['reds']) for d in recent]
    zone_tops = [max(zone_counts(d['reds'])) for d in recent]
    mean_sum = statistics.mean(sums)
    mean_ac = statistics.mean(acs)
    sum_cv = statistics.pstdev(sums) / mean_sum if mean_sum else 0.0
    ac_cv = statistics.pstdev(acs) / mean_ac if mean_ac else 0.0
    zone_dom = statistics.mean(zone_tops) / 6.0
    if sum_cv <= 0.12 and ac_cv <= 0.2 and zone_dom <= 0.45:
        return 'focus', {'sum_cv': round(sum_cv, 4), 'zone_dom': round(zone_dom, 4), 'ac_cv': round(ac_cv, 4)}
    if sum_cv >= 0.16 or ac_cv >= 0.28 or zone_dom >= 0.52:
        return 'fallback', {'sum_cv': round(sum_cv, 4), 'zone_dom': round(zone_dom, 4), 'ac_cv': round(ac_cv, 4)}
    return 'neutral', {'sum_cv': round(sum_cv, 4), 'zone_dom': round(zone_dom, 4), 'ac_cv': round(ac_cv, 4)}


def build_negative_profile(history, lookback=160, bottom_k=24):
    recent = history[-lookback:]
    if len(recent) < 20:
        return {'single_counts': Counter(), 'pair_counts': Counter(), 'triple_counts': Counter()}
    scored = []
    for idx in range(8, len(recent)):
        anchor = recent[idx]
        prev = recent[max(0, idx - 8):idx]
        sim = sum(similarity_score(anchor, d) for d in prev) / max(len(prev), 1)
        scored.append((sim, anchor))
    scored.sort(key=lambda x: x[0])
    sample_draws = [draw for _, draw in scored[:bottom_k]]
    single_counts = Counter()
    pair_counts = Counter()
    triple_counts = Counter()
    for draw in sample_draws:
        reds = sorted(draw['reds'])
        single_counts.update(reds)
        for pair in itertools.combinations(reds, 2):
            pair_counts[pair] += 1
        for triple in itertools.combinations(reds, 3):
            triple_counts[triple] += 1
    return {'single_counts': single_counts, 'pair_counts': pair_counts, 'triple_counts': triple_counts}


def build_red5_pseudo_targets(history, lookback=220, top_k=28):
    recent = history[-lookback:]
    if len(recent) < 36:
        return {'single_counts': Counter(), 'pair_counts': Counter(), 'triple_counts': Counter(), 'anchors': []}
    scored = []
    for idx in range(30, len(recent) - 1):
        current = recent[idx]
        nxt = recent[idx + 1]
        overlap = len(set(current['reds']) & set(nxt['reds']))
        if overlap < 2:
            continue
        shape_bonus = 0.0
        shape_bonus += 0.4 if abs(current['red_sum'] - nxt['red_sum']) <= 8 else 0.0
        shape_bonus += 0.25 if abs(ac_value(current['reds']) - ac_value(nxt['reds'])) <= 2 else 0.0
        shape_bonus += 0.2 if zone_counts(current['reds']) == zone_counts(nxt['reds']) else 0.0
        pseudo_score = overlap * 1.4 + shape_bonus
        scored.append((pseudo_score, current, nxt))
    scored.sort(reverse=True, key=lambda x: x[0])
    single_counts = Counter()
    pair_counts = Counter()
    triple_counts = Counter()
    anchors = []
    for _, current, nxt in scored[:top_k]:
        anchor_reds = sorted(set(current['reds']) | set(nxt['reds']))
        if len(anchor_reds) < 7:
            continue
        ranked = sorted(anchor_reds, key=lambda n: (n in nxt['reds'], n in current['reds'], -abs(n - statistics.mean(nxt['reds']))), reverse=True)
        core = sorted(ranked[:7])
        anchors.append(core)
        single_counts.update(core)
        for pair in itertools.combinations(core, 2):
            pair_counts[pair] += 1
        for triple in itertools.combinations(core, 3):
            triple_counts[triple] += 1
    return {'single_counts': single_counts, 'pair_counts': pair_counts, 'triple_counts': triple_counts, 'anchors': anchors}


def score_red_v5(n, hot10, hot30, hot100, cold50, omission, last_draw, metrics, target_profile, regime, red5_profile=None):
    score = score_red_v4(n, hot10, hot30, hot100, cold50, omission, last_draw, metrics, target_profile)
    omission_value = omission.get(n, 0)
    hot30_value = hot30.get(n, 0)
    hot100_value = hot100.get(n, 0)
    if 4 <= omission_value <= 8:
        score += 0.52
    elif omission_value >= 11:
        score -= 0.28
    if 12 <= n <= 22:
        score += 0.18
    elif n <= 4 or n >= 31:
        score -= 0.14
    if hot30_value >= 8 and hot100_value >= 18:
        score += 0.22
    if hot30_value <= 2 and omission_value <= 2:
        score -= 0.35
    if red5_profile:
        score += min(red5_profile.get('single_counts', Counter()).get(n, 0), 10) * 0.09
    if regime == 'focus':
        if 12 <= n <= 22:
            score += 0.28
        score += hot30_value * 0.05
    elif regime == 'fallback':
        if n in last_draw:
            score -= 0.18
        if omission_value >= 10:
            score -= 0.14
    return score


def build_blue_omission(history, limit=50):
    recent = history[-limit:]
    omission = {}
    for b in range(1, 17):
        gap = 0
        for draw in reversed(recent):
            if draw['blue'] == b:
                break
            gap += 1
        omission[b] = gap
    return omission


def pick_reds_v1(history):
    last30 = history[-30:]
    last50 = history[-50:]
    hot_counter = Counter()
    for draw in last30:
        hot_counter.update(draw['reds'])
    cold_counter = Counter({n: 0 for n in range(1, 34)})
    for n in range(1, 34):
        cold_counter[n] = 50 - sum(1 for draw in last50 if n in draw['reds'])
    sums = [d['red_sum'] for d in last30]
    odd_counts = [sum(1 for x in d['reds'] if x % 2 == 1) for d in last30]
    prime_counts = [sum(1 for x in d['reds'] if is_prime(x)) for d in last30]
    target_sum = median_or_default(sums, 96)
    odd_target = median_or_default(odd_counts, 3)
    prime_target = median_or_default(prime_counts, 2)
    last_draw = set(history[-1]['reds']) if history else set()
    red_scores = [(score_red_v1(n, hot_counter, cold_counter, last_draw, target_sum, odd_target, prime_target), n) for n in range(1, 34)]
    red_scores.sort(reverse=True)
    chosen = []
    for _, n in red_scores:
        trial = sorted(chosen + [n])
        if len(trial) > 7:
            continue
        odd = sum(1 for x in trial if x % 2 == 1)
        big = sum(1 for x in trial if x > 16)
        if len(trial) == 7:
            if not (2 <= odd <= 5 and 2 <= big <= 5):
                continue
            if not (target_sum - 18 <= sum(trial) <= target_sum + 18):
                continue
            if ac_value(trial) < 4:
                continue
        chosen = trial
        if len(chosen) == 7:
            break
    if len(chosen) < 7:
        chosen = sorted(n for _, n in red_scores[:7])
    blue_counter = Counter(draw['blue'] for draw in last30)
    blue_rank = [n for n, _ in sorted(blue_counter.items(), key=lambda kv: (-kv[1], kv[0]))]
    blues = blue_rank[:2] or [1, 6]
    return {
        'bet_type': '7红+2蓝复式',
        'reds': chosen,
        'blues': sorted(blues[:2]),
        'cost': 28,
        'bet_count': 14,
        'reason': {'target_sum': target_sum, 'odd_target': odd_target, 'prime_target': prime_target},
    }


def pick_reds_v2(history):
    metrics = quality_metrics(history[-50:])
    hot10, hot30, hot100, cold50, omission, blue10, blue30 = build_frequency_windows(history)
    last_draw = set(history[-1]['reds']) if history else set()
    red_scores = [(score_red_v2(n, hot10, hot30, cold50, omission, last_draw, metrics), n) for n in range(1, 34)]
    red_scores.sort(reverse=True)

    chosen = []
    for _, n in red_scores:
        trial = sorted(chosen + [n])
        if len(trial) > 8:
            continue
        odd = sum(1 for x in trial if x % 2 == 1)
        big = sum(1 for x in trial if x > 16)
        prime = sum(1 for x in trial if is_prime(x))
        zones = zone_counts(trial)
        if len(trial) == 8:
            s = sum(trial)
            if not (metrics['target_sum'] + 8 <= s <= metrics['target_sum'] + 34):
                continue
            if not (3 <= odd <= 5 and 3 <= big <= 5):
                continue
            if not (2 <= prime <= 4):
                continue
            if max(zones) > 4 or min(zones) < 1:
                continue
            ac = ac_value(trial)
            if not (6 <= ac <= 10):
                continue
        chosen = trial
        if len(chosen) == 8:
            break
    if len(chosen) < 8:
        chosen = sorted(n for _, n in red_scores[:8])

    blue_scores = []
    for b in range(1, 17):
        score = blue10.get(b, 0) * 1.1 + blue30.get(b, 0) * 0.7
        if b == history[-1]['blue']:
            score -= 0.6
        if b in {1, 6, 9, 10, 12, 16}:
            score += 0.15
        blue_scores.append((score, b))
    blue_scores.sort(reverse=True)
    blues = sorted([blue_scores[0][1]])
    return {
        'bet_type': '8红+1蓝复式',
        'reds': chosen,
        'blues': blues,
        'cost': 56,
        'bet_count': 28,
        'reason': {
            'target_sum': metrics['target_sum'],
            'odd_target': metrics['odd_target'],
            'big_target': metrics['big_target'],
            'prime_target': metrics['prime_target'],
            'ac_target': metrics['ac_target'],
            'zone_target': metrics['zone_target'],
        },
    }


def seasonal_profile(history, months=3):
    if not history:
        return {'blue_weights': Counter(), 'red_sum_median': 96, 'red_sum_low': 84, 'red_sum_high': 114}
    month = None
    for d in reversed(history):
        if d.get('draw_date'):
            month = int(d['draw_date'][5:7])
            break
    if month is None:
        return {'blue_weights': Counter(), 'red_sum_median': 96, 'red_sum_low': 84, 'red_sum_high': 114}
    allowed = {((month - 1 + delta - 1) % 12) + 1 for delta in range(months)}
    sample = [d for d in history if d.get('draw_date') and int(d['draw_date'][5:7]) in allowed]
    if len(sample) < 30:
        sample = history[-120:]
    blue_weights = Counter(d['blue'] for d in sample)
    red_sums = [d['red_sum'] for d in sample]
    red_sum_median = median_or_default(red_sums, 96)
    if len(red_sums) >= 4:
        q = statistics.quantiles(red_sums, n=4)
        red_sum_low = q[0]
        red_sum_high = q[2]
    else:
        red_sum_low = red_sum_median - 12
        red_sum_high = red_sum_median + 12
    return {
        'blue_weights': blue_weights,
        'red_sum_median': red_sum_median,
        'red_sum_low': red_sum_low,
        'red_sum_high': red_sum_high,
    }


def consecutive_shape_profile(combo):
    combo = sorted(combo)
    groups = []
    cur = [combo[0]]
    for n in combo[1:]:
        if n == cur[-1] + 1:
            cur.append(n)
        else:
            if len(cur) >= 2:
                groups.append(cur)
            cur = [n]
    if len(cur) >= 2:
        groups.append(cur)
    pair_groups = sum(1 for g in groups if len(g) == 2)
    triple_groups = sum(1 for g in groups if len(g) == 3)
    long_groups = sum(1 for g in groups if len(g) >= 4)
    return pair_groups, triple_groups, long_groups


def blue_state_score(b, blue10, blue30, blue_omission, last_blue, seasonal=None):
    hot_short = blue10.get(b, 0)
    hot_mid = blue30.get(b, 0)
    omission = blue_omission.get(b, 0)
    score = hot_short * 0.8 + hot_mid * 0.45
    if 4 <= omission <= 10:
        score += 1.2
    elif omission > 14:
        score -= 0.9
    elif omission <= 1:
        score -= 0.4
    if b == last_blue:
        score -= 0.5
    if b in {3, 8, 11}:
        score += 0.45
    if seasonal:
        score += min(seasonal.get('blue_weights', Counter()).get(b, 0), 18) * 0.025
    return score


def strongest_six_subset_score(combo, red_base_scores, metrics):
    best = None
    for subset in itertools.combinations(combo, 6):
        subset = sorted(subset)
        s = sum(subset)
        odd = sum(1 for x in subset if x % 2 == 1)
        big = sum(1 for x in subset if x > 16)
        prime = sum(1 for x in subset if is_prime(x))
        zones = zone_counts(subset)
        score = sum(red_base_scores[n] for n in subset)
        score -= abs(s - metrics['target_sum']) * 0.12
        score -= abs(odd - metrics['odd_target']) * 0.95
        score -= abs(big - metrics['big_target']) * 0.78
        score -= abs(prime - metrics['prime_target']) * 0.5
        score -= sum(abs(zones[i] - metrics['zone_target'][i]) * 0.82 for i in range(3))
        score -= abs(ac_value(subset) - metrics['ac_target']) * 0.18
        if best is None or score > best:
            best = score
    return best if best is not None else -999.0


def combo_dispersion_score(combo):
    combo = sorted(combo)
    gaps = [combo[i] - combo[i - 1] for i in range(1, len(combo))]
    even_gaps = sum(1 for g in gaps if 2 <= g <= 6)
    span = combo[-1] - combo[0]
    penalty = 0.0
    if span < 18:
        penalty += (18 - span) * 0.18
    elif span > 28:
        penalty += (span - 28) * 0.08
    if even_gaps < 4:
        penalty += (4 - even_gaps) * 0.35
    return -penalty


def combo_passes_filters(combo, metrics, last_draw, regime='neutral'):
    combo = sorted(combo)
    s = sum(combo)
    odd = sum(1 for x in combo if x % 2 == 1)
    big = sum(1 for x in combo if x > 16)
    prime = sum(1 for x in combo if is_prime(x))
    zones = zone_counts(combo)
    repeat_count = len(set(combo) & set(last_draw))
    mid_zone_count = sum(1 for x in combo if 12 <= x <= 22)
    low_zone_count = sum(1 for x in combo if x <= 11)
    high_zone_count = sum(1 for x in combo if x >= 23)
    pair_groups, triple_groups, long_groups = consecutive_shape_profile(combo)
    same_tail_groups = same_tail_group_count(combo)

    if not (90 <= s <= 120):
        return False
    if odd not in {2, 3, 4}:
        return False
    if prime != 2:
        return False
    if max(zones) > (3 if regime != 'fallback' else 4) or min(zones) < 1:
        return False
    if mid_zone_count < (2 if regime != 'fallback' else 1):
        return False
    if low_zone_count == 0 or high_zone_count == 0:
        return False
    if pair_groups < 1:
        return False
    if triple_groups >= 1 or long_groups >= 1:
        return False
    if pair_groups > 1:
        return False
    if repeat_count > (1 if regime == 'focus' else 2):
        return False
    if tail_count(combo) > 2:
        return False
    if same_tail_groups < 1:
        return False
    ac = ac_value(combo)
    if ac not in {7, 8, 9}:
        return False
    if combo[-1] - combo[0] < 16:
        return False
    return True


def combo_red5_bonus(combo, red5_profile):
    if not red5_profile:
        return 0.0
    bonus = 0.0
    single_counts = red5_profile.get('single_counts', Counter())
    pair_counts = red5_profile.get('pair_counts', Counter())
    triple_counts = red5_profile.get('triple_counts', Counter())
    for n in combo:
        bonus += min(single_counts.get(n, 0), 8) * 0.05
    for pair in itertools.combinations(sorted(combo), 2):
        bonus += min(pair_counts.get(pair, 0), 4) * 0.08
    for triple in itertools.combinations(sorted(combo), 3):
        bonus += min(triple_counts.get(triple, 0), 3) * 0.12
    return min(bonus, 3.4)


def combo_score(combo, red_base_scores, metrics, last_draw, pair_counts=None, regime='neutral', negative_profile=None, red5_profile=None, seasonal=None):
    combo = sorted(combo)
    red_core = sum(red_base_scores[n] for n in combo)
    six_core = strongest_six_subset_score(combo, red_base_scores, metrics)
    s = sum(combo)
    odd = sum(1 for x in combo if x % 2 == 1)
    big = sum(1 for x in combo if x > 16)
    prime = sum(1 for x in combo if is_prime(x))
    zones = zone_counts(combo)
    struct_penalty = 0.0
    struct_penalty += abs(s - metrics['target_sum']) * 0.08
    struct_penalty += abs(odd - metrics['odd_target']) * 0.72
    struct_penalty += abs(big - metrics['big_target']) * 0.66
    struct_penalty += abs(prime - metrics['prime_target']) * 0.45
    struct_penalty += sum(abs(zones[i] - metrics['zone_target'][i]) * 0.55 for i in range(3))
    struct_penalty += abs(ac_value(combo) - metrics['ac_target']) * 0.16
    stability = 0.0
    repeat_count = len(set(combo) & set(last_draw))
    if repeat_count == 0:
        stability += 0.18
    elif repeat_count == 1:
        stability += 0.08
    else:
        stability -= repeat_count * 0.22
    mid_zone_count = sum(1 for x in combo if 12 <= x <= 22)
    stability += mid_zone_count * 0.1
    risk = 0.0
    if consecutive_groups(combo) == 0:
        risk += 0.05
    if tail_count(combo) >= 2:
        risk += 0.12 * tail_count(combo)
    synergy = 0.0
    if pair_counts:
        pair_score = sum(pair_counts.get(tuple(sorted(pair)), 0) for pair in itertools.combinations(combo, 2))
        synergy += min(pair_score / (10.0 if regime == 'focus' else 14.0), 2.8 if regime == 'focus' else 2.0)
    negative_penalty = 0.0
    if negative_profile:
        neg_pair = negative_profile.get('pair_counts', Counter())
        neg_triple = negative_profile.get('triple_counts', Counter())
        neg_singles = negative_profile.get('single_counts', Counter())
        for n in combo:
            negative_penalty += min(neg_singles.get(n, 0), 8) * 0.035
        for pair in itertools.combinations(sorted(combo), 2):
            negative_penalty += min(neg_pair.get(pair, 0), 4) * 0.05
        for triple in itertools.combinations(sorted(combo), 3):
            negative_penalty += min(neg_triple.get(triple, 0), 3) * 0.08
    pair_groups, triple_groups, long_groups = consecutive_shape_profile(combo)
    consecutive_bonus = 0.0
    if pair_groups == 1 and triple_groups == 0 and long_groups == 0:
        consecutive_bonus += 0.42
    elif pair_groups == 2 and triple_groups == 0 and long_groups == 0:
        consecutive_bonus -= 0.08
    elif triple_groups >= 1 or long_groups >= 1:
        consecutive_bonus -= 0.2 * triple_groups + 0.35 * long_groups
    seasonal_bonus = 0.0
    if seasonal:
        s = sum(combo)
        seasonal_bonus -= abs(s - seasonal.get('red_sum_median', metrics['target_sum'])) * 0.018
        low = seasonal.get('red_sum_low', metrics['target_sum'] - 12)
        high = seasonal.get('red_sum_high', metrics['target_sum'] + 12)
        if low <= s <= high:
            seasonal_bonus += 0.16
        else:
            seasonal_bonus -= 0.08
    dispersion = combo_dispersion_score(combo)
    red5_bonus = combo_red5_bonus(combo, red5_profile)
    if regime == 'focus':
        stability += 0.18
    elif regime == 'fallback':
        risk *= 0.7
        struct_penalty *= 0.9
    return six_core * 1.42 + red_core * 0.32 + stability + synergy + dispersion + red5_bonus + consecutive_bonus + seasonal_bonus - struct_penalty - risk - negative_penalty


def pick_reds_v3(history, single_blue=False, candidate_mode='v3'):
    metrics = quality_metrics(history[-100:] if len(history) >= 100 else history[-50:])
    hot10, hot30, hot100, cold50, omission, blue10, blue30 = build_frequency_windows(history)
    blue_omission = build_blue_omission(history)
    pair_counts = build_pair_counts(history)
    regime, regime_info = compute_regime(history)
    seasonal = seasonal_profile(history)
    target_profile = build_target_profile(history) if candidate_mode in {'v4', 'v5', 'v5.2'} else None
    negative_profile = build_negative_profile(history) if candidate_mode in {'v5', 'v5.2'} else None
    red5_profile = build_red5_pseudo_targets(history) if candidate_mode == 'v5.2' else None
    last_draw = history[-1]['reds'] if history else []
    last_blue = history[-1]['blue'] if history else None

    red_rank = []
    red_base_scores = {}
    for n in range(1, 34):
        if candidate_mode == 'v5.2':
            score = score_red_v5(n, hot10, hot30, hot100, cold50, omission, set(last_draw), metrics, target_profile, regime, red5_profile=red5_profile)
        elif candidate_mode == 'v5':
            score = score_red_v5(n, hot10, hot30, hot100, cold50, omission, set(last_draw), metrics, target_profile, regime)
        elif candidate_mode == 'v4':
            score = score_red_v4(n, hot10, hot30, hot100, cold50, omission, set(last_draw), metrics, target_profile)
        elif candidate_mode == 'v3.3':
            score = score_red_v33(n, hot10, hot30, hot100, cold50, omission, set(last_draw), metrics)
        else:
            score = score_red_v3(n, hot10, hot30, cold50, omission, set(last_draw), metrics)
        red_base_scores[n] = score
        red_rank.append((score, n))
    red_rank.sort(reverse=True)
    pool_size = 11 if candidate_mode == 'v5.2' and regime == 'focus' else 13 if candidate_mode == 'v5.2' else 12 if candidate_mode == 'v5' and regime == 'focus' else 15 if candidate_mode == 'v5' and regime == 'fallback' else 14 if candidate_mode == 'v5' else 15
    candidate_pool = [n for _, n in red_rank[:pool_size]]
    a_layer = sorted(candidate_pool[:5])
    b_layer = sorted(candidate_pool[5:10])
    c_layer = sorted(candidate_pool[10:])

    combos = []
    for combo in itertools.combinations(candidate_pool, 7):
        count_a = sum(1 for x in combo if x in a_layer)
        count_b = sum(1 for x in combo if x in b_layer)
        count_c = sum(1 for x in combo if x in c_layer)
        if not (3 <= count_a <= 4):
            continue
        if not (2 <= count_b <= 3):
            continue
        if not (1 <= count_c <= 2):
            continue
        if not combo_passes_filters(combo, metrics, last_draw, regime=regime):
            continue
        score = combo_score(combo, red_base_scores, metrics, last_draw, pair_counts, regime=regime, negative_profile=negative_profile, red5_profile=red5_profile, seasonal=seasonal)
        if candidate_mode in {'v4', 'v5', 'v5.2'} and target_profile:
            score += target_combo_bonus(combo, target_profile)
        combos.append((score, tuple(sorted(combo))))
    combos.sort(reverse=True)
    best_combo = list(combos[0][1]) if combos else sorted(candidate_pool[:7])

    blue_scores = []
    preferred_blue_pool = {3, 8, 11}
    for b in range(1, 17):
        score = blue_state_score(b, blue10, blue30, blue_omission, last_blue, seasonal=seasonal)
        blue_scores.append((score, b))
    blue_scores.sort(reverse=True)
    filtered_blue_scores = [item for item in blue_scores if item[1] in preferred_blue_pool]
    if single_blue:
        blue_candidates = [filtered_blue_scores[0][1] if filtered_blue_scores else blue_scores[0][1]]
    else:
        top_pool = filtered_blue_scores[:2] if len(filtered_blue_scores) >= 2 else blue_scores[:2]
        blue_candidates = sorted([x[1] for x in top_pool])

    return {
        'bet_type': '7红+1蓝复式' if single_blue else '7红+2蓝复式',
        'reds': best_combo,
        'blues': blue_candidates,
        'cost': 14 if single_blue else 28,
        'bet_count': 7 if single_blue else 14,
        'reason': {
            'target_sum': metrics['target_sum'],
            'odd_target': metrics['odd_target'],
            'big_target': metrics['big_target'],
            'prime_target': metrics['prime_target'],
            'ac_target': metrics['ac_target'],
            'zone_target': metrics['zone_target'],
            'candidate_pool': candidate_pool,
            'a_layer': a_layer,
            'b_layer': b_layer,
            'c_layer': c_layer,
            'combo_count': len(combos),
            'blue_rank': [b for _, b in (filtered_blue_scores[:4] if filtered_blue_scores else blue_scores[:4])],
            'regime': regime,
            'regime_info': regime_info,
            'seasonal_red_sum_median': seasonal['red_sum_median'],
            'seasonal_red_sum_low': round(seasonal['red_sum_low'], 1),
            'seasonal_red_sum_high': round(seasonal['red_sum_high'], 1),
        },
    }


def target_combo_bonus(combo, target_profile):
    pair_counts = target_profile.get('pair_counts', Counter())
    triple_counts = target_profile.get('triple_counts', Counter())
    bonus = 0.0
    for pair in itertools.combinations(sorted(combo), 2):
        bonus += min(pair_counts.get(pair, 0), 4) * 0.08
    for triple in itertools.combinations(sorted(combo), 3):
        bonus += min(triple_counts.get(triple, 0), 3) * 0.12
    return min(bonus, 2.6)


def build_strategy(history, strategy_version):
    if strategy_version == 'cp-v5.3':
        return pick_reds_v3(history, single_blue=True, candidate_mode='v5.2')
    if strategy_version == 'cp-v5.2':
        return pick_reds_v3(history, single_blue=True, candidate_mode='v5.2')
    if strategy_version == 'cp-v5.1':
        return pick_reds_v3(history, single_blue=True, candidate_mode='v5')
    if strategy_version == 'cp-v5':
        return pick_reds_v3(history, single_blue=True, candidate_mode='v5')
    if strategy_version == 'cp-v4':
        return pick_reds_v3(history, single_blue=True, candidate_mode='v4')
    if strategy_version == 'cp-v3.3':
        return pick_reds_v3(history, single_blue=True, candidate_mode='v3.3')
    if strategy_version == 'cp-v3.2':
        return pick_reds_v3(history, single_blue=True)
    if strategy_version == 'cp-v3' or strategy_version == 'cp-v3.1':
        return pick_reds_v3(history)
    if strategy_version == 'cp-v2':
        return pick_reds_v2(history)
    return pick_reds_v1(history)


def evaluate(strategy, draw):
    hit_red = len(set(strategy['reds']) & set(draw['reds']))
    hit_blue = draw['blue'] in strategy['blues']
    prize_level, per_bet_return = PRIZE_MAP.get((hit_red, hit_blue), ('未中奖', 0))
    multiplier = len(strategy['blues']) if hit_red >= 6 else 1
    return_amount = per_bet_return * multiplier
    return hit_red, hit_blue, prize_level, return_amount


def second_prize_proxy(hit_red, hit_blue):
    if hit_red == 5 and hit_blue:
        return 2.0
    if hit_red == 6 and not hit_blue:
        return 1.5
    if hit_red == 5 and not hit_blue:
        return 1.0
    if hit_red == 4 and hit_blue:
        return 0.6
    if hit_red == 4 and not hit_blue:
        return 0.25
    return 0.0


def review(strategy, draw, hit_red, hit_blue):
    red_sum = sum(strategy['reds'])
    actual_sum = draw['red_sum']
    parts = []
    if red_sum < actual_sum - 10:
        parts.append('本期预测红球和值偏低')
    elif red_sum > actual_sum + 10:
        parts.append('本期预测红球和值偏高')
    else:
        parts.append('本期和值判断大体在常见区间')
    odd = sum(1 for x in strategy['reds'] if x % 2 == 1)
    actual_odd = sum(1 for x in draw['reds'] if x % 2 == 1)
    if odd != actual_odd:
        parts.append('奇偶结构和真实开奖有偏差')
    if not hit_blue:
        parts.append('蓝球防守失误')
    else:
        parts.append('蓝球防守命中')
    if hit_red < 4:
        parts.append('红球覆盖强度不足，二区或尾数组合不够顺')
    elif hit_red == 5 and not hit_blue:
        parts.append('红球主框架接近，但蓝球未跟上，离二等奖只差关键一步')
    elif hit_red >= 5 and hit_blue:
        parts.append('主结构已经接近高奖方向，说明框架在变稳')
    else:
        parts.append('结构不算差，但还没形成足够强的命中闭环')
    next_adj = '下期继续优先控制和值区间、三区均衡与蓝球节奏切换，避免追热与极冷赌博。'
    return '；'.join(parts), next_adj


def run_backtest(conn, start_issue=None, end_issue=None, limit=None, strategy_version='cp-v1'):
    draws = load_draws(conn)
    if start_issue:
        draws = [d for d in draws if d['issue_code'] >= start_issue]
    if end_issue:
        draws = [d for d in draws if d['issue_code'] <= end_issue]
    if limit:
        draws = draws[:limit]
    history = []
    run_id = str(uuid.uuid4())
    total_budget = 0
    total_return = 0
    second_hits = 0
    proxy_total = 0.0
    high_red_hits = 0
    blue_hits = 0
    now = datetime.now(timezone.utc).isoformat()
    details = []

    for draw in draws:
        if len(history) < 30:
            history.append(draw)
            continue
        strategy = build_strategy(history, strategy_version)
        hit_red, hit_blue, prize_level, return_amount = evaluate(strategy, draw)
        proxy_total += second_prize_proxy(hit_red, hit_blue)
        if hit_red >= 5:
            high_red_hits += 1
        if hit_blue:
            blue_hits += 1
        review_note, next_adjustment = review(strategy, draw, hit_red, hit_blue)
        total_budget += strategy['cost']
        total_return += return_amount
        if prize_level == '二等奖':
            second_hits += 1
        details.append((
            run_id, draw['issue_code'], draw['draw_date'], len(history),
            strategy['bet_type'], ','.join(f'{x:02d}' for x in strategy['reds']), ','.join(f'{x:02d}' for x in strategy['blues']),
            json.dumps(strategy, ensure_ascii=False), strategy['bet_count'], strategy['cost'],
            hit_red, 1 if hit_blue else 0, prize_level, return_amount,
            review_note, next_adjustment, now,
        ))
        history.append(draw)

    if not details:
        raise SystemExit('样本不足，至少需要 31 期数据才能开始回测。')

    conn.executemany('''
      INSERT OR REPLACE INTO backtest_details (
        run_id, issue_code, draw_date, history_count, bet_type, red_candidates, blue_candidates,
        chosen_numbers_json, bet_count, cost, hit_red, hit_blue, prize_level, return_amount,
        review_note, next_adjustment, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', details)
    notes = {
        'sample': len(details),
        'second_prize_proxy': round(proxy_total, 2),
        'red5_plus_hits': high_red_hits,
        'blue_hit_rate': round(blue_hits / len(details), 4),
    }
    conn.execute('''
      INSERT OR REPLACE INTO backtest_runs (
        run_id, strategy_version, start_issue, end_issue, issue_count, total_budget,
        total_return, second_prize_hits, notes_json, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        run_id, strategy_version, details[0][1], details[-1][1], len(details), total_budget,
        total_return, second_hits, json.dumps(notes, ensure_ascii=False), now,
    ))
    conn.commit()
    return run_id


def summarize(conn, run_id):
    cur = conn.cursor()
    run = cur.execute('SELECT strategy_version, start_issue, end_issue, issue_count, total_budget, total_return, second_prize_hits, notes_json FROM backtest_runs WHERE run_id=?', (run_id,)).fetchone()
    prizes = cur.execute('SELECT prize_level, COUNT(*), SUM(return_amount) FROM backtest_details WHERE run_id=? GROUP BY prize_level ORDER BY COUNT(*) DESC', (run_id,)).fetchall()
    samples = cur.execute('SELECT issue_code, bet_type, red_candidates, blue_candidates, prize_level, return_amount, review_note FROM backtest_details WHERE run_id=? ORDER BY issue_code ASC LIMIT 5', (run_id,)).fetchall()
    notes = json.loads(run[7] or '{}')
    return {
        'run_id': run_id,
        'strategy_version': run[0],
        'range': [run[1], run[2]],
        'issue_count': run[3],
        'total_budget': run[4],
        'total_return': run[5],
        'net': run[5] - run[4],
        'second_prize_hits': run[6],
        'second_prize_proxy': notes.get('second_prize_proxy', 0),
        'red5_plus_hits': notes.get('red5_plus_hits', 0),
        'blue_hit_rate': notes.get('blue_hit_rate', 0),
        'prizes': [{'prize_level': p[0], 'count': p[1], 'return_amount': p[2] or 0} for p in prizes],
        'samples': [
            {
                'issue_code': s[0],
                'bet_type': s[1],
                'reds': s[2],
                'blues': s[3],
                'prize_level': s[4],
                'return_amount': s[5],
                'review_note': s[6],
            } for s in samples
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=DB_PATH)
    parser.add_argument('--start-issue', default='')
    parser.add_argument('--end-issue', default='')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--strategy-version', default='cp-v1')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    ensure_tables(conn)
    run_id = run_backtest(
        conn,
        start_issue=args.start_issue or None,
        end_issue=args.end_issue or None,
        limit=args.limit or None,
        strategy_version=args.strategy_version,
    )
    print(json.dumps(summarize(conn, run_id), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
