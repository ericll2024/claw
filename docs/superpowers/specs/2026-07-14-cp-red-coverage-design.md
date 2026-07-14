# CP Red-Ball Coverage Evaluation Design

## Goal

Optimize the selection of existing 8, 9, 10, and 11-red-ball pools for red-ball coverage only. The system must not claim that it can predict a random draw or guarantee a positive return.

## Baseline and Measurement

Each pool is measured as a set of red balls against the following draw. The core metrics are mean red hits, red 4+ rate, red 5+ rate, and complete six-red coverage. Results are compared with a deterministic random baseline using the same red-pool size; the theoretical expected mean is `6 * pool_size / 33`.

Evaluation uses a walk-forward split:

- A 300-draw development window produces candidate feature weights.
- The following 100 draws are a holdout window; they must not influence the chosen weights.
- The candidate may become the production strategy only if it improves both mean red hits and red 5+ rate against the current strategy and random baseline on the holdout window. Otherwise production remains on the current strategy.

## Candidate Strategy

The candidate ranks every red ball using a regularized, recency-weighted score:

- exponentially decayed frequency over the recent 10, 30, and 100 draws;
- a bounded omission signal that neither rewards very long absences nor assumes a number is due;
- a weak last-draw recurrence signal;
- a deterministic tie-breaker.

The score is deliberately limited to univariate historical features. Sum, odd/even, zone, pair, and triple rules remain only in the current strategy comparator because adding them to the candidate without out-of-sample evidence would increase overfitting risk.

## Selection and Rollout

The evaluator compares the current production ranking, the candidate red ranking, and deterministic random pools. It emits auditable per-tier results plus a recommendation: `candidate`, `current`, or `no_evidence`.

Prediction generation uses the candidate only when a persisted evaluation record has recommendation `candidate`; otherwise it keeps the current `cp-v5.4` strategy. Blue-ball selection remains unchanged: exactly one blue ball is included per plan and it is not used in the red-ball comparison.

## Constraints

- Preserve all existing purchase tiers and their costs.
- Do not alter or delete historical prediction plans.
- Do not use future draws when computing any prediction or evaluation row.
- Do not present backtest performance as a promise of future lottery returns.

## Testing

Tests verify no-lookahead walk-forward evaluation, deterministic random baselines, correct theoretical expectation, candidate selection gates, and that production falls back to the current strategy without qualifying evidence.
