---
name: backtest-analyzer
description: Interprets EA backtest results and provides actionable analysis. Evaluates metrics against thresholds, identifies weaknesses, and scores strategy quality.
---

# Backtest Results Analyzer

You are an expert at analyzing trading strategy backtest results. You interpret metrics, identify weaknesses, and provide actionable insights.

## When to Use This Skill

Claude automatically uses this skill when:
- A user asks about backtest results
- After running a backtest via the stress-test pipeline
- When evaluating EA performance
- When comparing multiple EAs

## Supporting Files

- **metrics.md** - Detailed explanation of each metric
- **scoring.md** - How to score and rank EAs

## Analysis Process

### 1. Read the Metrics
Parse the backtest report to extract:
```python
from parser.report import ReportParser
parser = ReportParser()
metrics = parser.parse(Path("path/to/report.html"))
```

Key metrics to analyze:
- Profit Factor
- Win Rate
- Maximum Drawdown
- Recovery Factor
- Sharpe Ratio
- Total Trades

### 2. Apply Thresholds
Load configurable thresholds from settings:
```python
from settings import get_settings
settings = get_settings()

# Check against thresholds
is_good = (
    metrics.profit_factor >= settings.thresholds.min_profit_factor and
    metrics.max_drawdown_pct <= settings.thresholds.max_drawdown_pct and
    metrics.total_trades >= settings.thresholds.min_trades
)
```

### 3. Identify Weaknesses
Look for these red flags:

| Issue | Indicator | Concern |
|-------|-----------|---------|
| Overfitting | Very high PF (>5) with few trades | May not work in live trading |
| Low sample size | <50 trades | Results not statistically significant |
| High drawdown | >30% | Risk of blowing account |
| Poor recovery | Recovery Factor <1 | Takes too long to recover from losses |
| Low win rate | <40% with PF<1.5 | May have psychological issues in live trading |
| Negative Sharpe | <0 | Strategy loses money risk-adjusted |

### 4. Consider Context
Ask these questions:

1. **Market conditions**: Was this during trending or ranging markets?
2. **Trade frequency**: Is this enough trades for statistical significance?
3. **Time distribution**: Are profits concentrated in specific periods?
4. **Correlation with market**: Does it work in both up and down markets?

### 5. Generate Insights

Provide specific, actionable feedback:

**GOOD Example:**
> The EA has a profit factor of 1.8 with 145 trades over 4 years. This is statistically significant. However, the max drawdown of 35% is concerning - consider adding a trailing stop or reducing position size.

**BAD Example:**
> The results look okay.

## Quick Assessment Table

| Metric | Poor | Acceptable | Good | Excellent |
|--------|------|------------|------|-----------|
| Profit Factor | <1.0 | 1.0-1.5 | 1.5-2.5 | >2.5 |
| Win Rate | <35% | 35-50% | 50-65% | >65% |
| Max Drawdown | >40% | 25-40% | 15-25% | <15% |
| Recovery Factor | <0.5 | 0.5-1.5 | 1.5-3.0 | >3.0 |
| Sharpe Ratio | <0 | 0-0.5 | 0.5-1.5 | >1.5 |
| Total Trades | <30 | 30-100 | 100-500 | >500 |

## Analysis Report Template

When analyzing results, structure your report as:

```
## Backtest Analysis: [EA Name]

### Overall Score: [X/10]
[One sentence summary]

### Key Metrics
| Metric | Value | Status |
|--------|-------|--------|
| Profit Factor | X.XX | [emoji] Good/Poor |
| ...

### Strengths
- [Bullet point strengths]

### Weaknesses
- [Bullet point weaknesses]

### Recommendations
1. [Specific actionable improvement]
2. [Another improvement]

### Robustness Assessment
- Monte Carlo Confidence: X%
- Multi-pair performance: X/5 pairs profitable
- Risk of ruin: X%
```

## Integration with Pipeline

This skill works with:
- `parser/report.py` - Extract metrics from HTML reports
- `tester/montecarlo.py` - Robustness testing
- `tester/multipair.py` - Multi-pair validation
- `settings.py` - Configurable thresholds
