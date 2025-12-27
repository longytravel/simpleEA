# EA Scoring and Ranking System

How to score and compare Expert Advisors objectively.

## Scoring Philosophy

The goal is to find EAs that:
1. Are profitable (Profit Factor > 1.5)
2. Manage risk well (Drawdown < 30%)
3. Are statistically robust (Many trades, Monte Carlo passes)
4. Work across conditions (Multi-pair validation)

## Primary Scoring Formula

```python
def calculate_score(metrics, mc_result=None, multipair_result=None):
    """
    Calculate composite EA score (0-100 scale).
    """
    # Load weights from settings
    from settings import get_settings
    weights = get_settings().scoring

    score = 0.0

    # Profit Factor (0-30 points)
    # Capped at 3.0 to avoid rewarding overfitting
    pf_capped = min(metrics.profit_factor, 3.0)
    pf_score = (pf_capped / 3.0) * 30 * (weights.profit_factor / 20)
    score += pf_score

    # Recovery Factor (0-20 points)
    # Capped at 5.0
    rf_capped = min(metrics.recovery_factor, 5.0)
    rf_score = (rf_capped / 5.0) * 20 * (weights.recovery_factor / 15)
    score += rf_score

    # Win Rate (0-10 points)
    # Optimal around 50%, penalize extremes
    wr_optimal = 100 - abs(metrics.win_rate - 50) * 2
    wr_score = (wr_optimal / 100) * 10 * (weights.win_rate / 10)
    score += wr_score

    # Drawdown (0-15 points, lower is better)
    # 0% DD = 15 points, 50% DD = 0 points
    dd_score = max(0, (50 - metrics.max_drawdown_pct) / 50 * 15)
    dd_score *= abs(weights.max_drawdown) / 2
    score += dd_score

    # Sharpe Ratio (0-10 points)
    # Capped at 2.0
    sharpe_capped = max(0, min(metrics.sharpe_ratio, 2.0))
    sharpe_score = (sharpe_capped / 2.0) * 10 * (weights.sharpe_ratio / 5)
    score += sharpe_score

    # Trade Count Bonus (0-5 points)
    # More trades = more confidence
    trade_bonus = min(metrics.total_trades / 500, 1.0) * 5
    trade_bonus *= (weights.total_trades / 0.1)
    score += trade_bonus

    # Monte Carlo Bonus (0-5 points)
    if mc_result and mc_result.confidence_level > 0:
        mc_bonus = (mc_result.confidence_level / 100) * 5
        mc_bonus *= (weights.monte_carlo_confidence / 10)
        score += mc_bonus

    # Multi-Pair Bonus (0-5 points)
    if multipair_result:
        mp_ratio = multipair_result.pairs_profitable / len(multipair_result.pairs_tested)
        mp_bonus = mp_ratio * 5
        score += mp_bonus

    return min(score, 100)  # Cap at 100
```

## Scoring Categories

| Score | Category | Description |
|-------|----------|-------------|
| 0-20 | Reject | Not viable, don't waste time |
| 20-40 | Poor | Major issues, needs significant work |
| 40-60 | Acceptable | Has potential, needs refinement |
| 60-80 | Good | Solid strategy, minor improvements needed |
| 80-100 | Excellent | Production-ready candidate |

## Leaderboard Structure

```json
{
  "leaderboard": [
    {
      "rank": 1,
      "ea_name": "MA_15_60_EURUSD_H1_20241226",
      "score": 85.5,
      "metrics": {
        "profit_factor": 2.1,
        "win_rate": 52.3,
        "max_drawdown_pct": 18.5,
        "recovery_factor": 3.2,
        "sharpe_ratio": 1.4,
        "total_trades": 234
      },
      "robustness": {
        "monte_carlo_confidence": 78.5,
        "pairs_profitable": 4,
        "pairs_tested": 5
      },
      "timestamp": "2024-12-26T12:30:00",
      "parameters": {
        "fast_period": 15,
        "slow_period": 60
      }
    }
  ]
}
```

## Ranking Rules

### Primary Sort
Sort by composite score (descending)

### Tiebreakers (in order)
1. Monte Carlo confidence
2. Recovery Factor
3. Profit Factor
4. Lower drawdown

### Automatic Disqualification
An EA is removed from consideration if:
- Profit Factor < 1.0 (losing money)
- Total Trades < 30 (not enough data)
- Max Drawdown > 50% (too risky)
- Monte Carlo Confidence < 50% (not robust)

## Comparative Analysis

When comparing two EAs:

```
EA A vs EA B Comparison
-----------------------
Metric          | EA A    | EA B    | Winner
----------------|---------|---------|--------
Profit Factor   | 1.8     | 2.1     | EA B
Win Rate        | 55%     | 45%     | EA A
Max Drawdown    | 22%     | 28%     | EA A
Recovery Factor | 2.5     | 2.2     | EA A
Sharpe Ratio    | 1.1     | 1.3     | EA B
Total Trades    | 180     | 220     | EA B
MC Confidence   | 75%     | 82%     | EA B
----------------|---------|---------|--------
Overall Score   | 72.5    | 75.8    | EA B

Winner: EA B (higher score, more robust)
```

## Score Evolution Tracking

Track how an EA's score changes as improvements are made:

```
Iteration | Score | Change | What Changed
----------|-------|--------|-------------
v1        | 45.2  | -      | Initial version
v2        | 52.1  | +6.9   | Added trailing stop
v3        | 58.3  | +6.2   | Optimized MA periods
v4        | 61.7  | +3.4   | Added time filter
v5        | 68.9  | +7.2   | Reduced lot size, lower DD
```

## When to Stop Improving

An EA is "good enough" when:
- Score > 70
- Monte Carlo Confidence > 70%
- At least 3/5 pairs profitable
- Profit Factor > 1.5 on primary pair
- Max Drawdown < 30%

Further optimization may lead to overfitting.
