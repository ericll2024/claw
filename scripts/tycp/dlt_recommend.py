import argparse
import json
from itertools import combinations
from pathlib import Path

DB_PATH = Path('/home/eric/Documents/workspace/state/tycp/data/dlt_history.sqlite3')

DEFAULT_FRONT_POOL = [8, 11, 12, 13, 18, 19, 20, 21, 22, 23, 24, 25, 28, 29, 30]
DEFAULT_BACK_POOL = [3, 8, 11, 12]

SUM_RANGE = (70, 120)
SUM_PREFERRED = (80, 110)
PREFERRED_AC = {4, 5, 6}
PREFERRED_FRONT_ODD_EVEN = {(3, 2), (2, 3)}
PREFERRED_BACK_ODD_EVEN = {(1, 1)}


def fmt(nums):
    return [f'{n:02d}' for n in nums]


def odd_even_counts(nums):
    odd = sum(n % 2 for n in nums)
    even = len(nums) - odd
    return odd, even


def has_consecutive_pair(nums):
    nums = sorted(nums)
    return any(b - a == 1 for a, b in zip(nums, nums[1:]))


def ac_value(nums):
    nums = sorted(nums)
    diffs = {nums[j] - nums[i] for i in range(len(nums)) for j in range(i + 1, len(nums))}
    return len(diffs) - (len(nums) - 1)


def front_score(nums):
    total = sum(nums)
    odd_even = odd_even_counts(nums)
    ac = ac_value(nums)
    consecutive = has_consecutive_pair(nums)

    if not (SUM_RANGE[0] <= total <= SUM_RANGE[1]):
        return None
    if odd_even not in PREFERRED_FRONT_ODD_EVEN:
        return None
    if not consecutive:
        return None
    if ac not in PREFERRED_AC:
        return None

    score = 0
    if SUM_PREFERRED[0] <= total <= SUM_PREFERRED[1]:
        score += 3
    score += 2 if ac in PREFERRED_AC else 0
    score += 1 if consecutive else 0

    mid_hits = sum(12 <= n <= 29 for n in nums)
    score += mid_hits

    return {
        'front': nums,
        'sum': total,
        'odd_even': odd_even,
        'ac': ac,
        'score': score,
    }


def back_score(nums):
    odd_even = odd_even_counts(nums)
    if odd_even not in PREFERRED_BACK_ODD_EVEN:
        return None
    return {
        'back': nums,
        'odd_even': odd_even,
        'score': 1,
    }


def recommend(front_pool, back_pool, limit):
    front_candidates = []
    for combo in combinations(sorted(set(front_pool)), 5):
        scored = front_score(list(combo))
        if scored:
            front_candidates.append(scored)

    back_candidates = []
    for combo in combinations(sorted(set(back_pool)), 2):
        scored = back_score(list(combo))
        if scored:
            back_candidates.append(scored)

    front_candidates.sort(key=lambda x: (-x['score'], abs(95 - x['sum']), x['front']))
    back_candidates.sort(key=lambda x: (x['back']))

    results = []
    used_patterns = set()
    for front in front_candidates:
        for back in back_candidates:
            pattern = tuple(n in front['front'] for n in [12, 19, 22, 24, 29])
            key = (tuple(front['front']), tuple(back['back']))
            if key in used_patterns:
                continue
            used_patterns.add(key)
            results.append({
                'front': fmt(front['front']),
                'back': fmt(back['back']),
                'front_sum': front['sum'],
                'front_odd_even': list(front['odd_even']),
                'back_odd_even': list(back['odd_even']),
                'front_ac': front['ac'],
                'has_consecutive_pair': True,
                'score': front['score'] + back['score'],
                'core_pattern': pattern,
            })
            if len(results) >= limit:
                return results
    return results


def parse_pool(text, default):
    if not text:
        return default
    return [int(x) for x in str(text).replace(',', ' ').split() if x.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--front-pool', default='')
    parser.add_argument('--back-pool', default='')
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()

    front_pool = parse_pool(args.front_pool, DEFAULT_FRONT_POOL)
    back_pool = parse_pool(args.back_pool, DEFAULT_BACK_POOL)

    result = {
        'db_path': str(DB_PATH),
        'rules': {
            'front_sum_range': list(SUM_RANGE),
            'front_sum_preferred': list(SUM_PREFERRED),
            'front_odd_even': [list(x) for x in sorted(PREFERRED_FRONT_ODD_EVEN)],
            'back_odd_even': [list(x) for x in sorted(PREFERRED_BACK_ODD_EVEN)],
            'require_consecutive_pair': True,
            'front_ac_preferred': sorted(PREFERRED_AC),
        },
        'front_pool': fmt(sorted(set(front_pool))),
        'back_pool': fmt(sorted(set(back_pool))),
        'recommendations': recommend(front_pool, back_pool, args.limit),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
