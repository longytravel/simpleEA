# Backtest Metrics Explained

Detailed explanation of each trading metric and how to interpret it.

## Profitability Metrics

### Profit Factor (PF)
**Definition:** Gross Profit / Gross Loss (absolute value)

**Interpretation:**
- PF = 1.0: Break-even
- PF > 1.0: Profitable
- PF > 2.0: Strong strategy
- PF > 3.0: Exceptional (verify not overfitted)

**Calculation:**
```
PF = Sum of all winning trades / |Sum of all losing trades|
```

**Watch out for:**
- Very high PF (>5) with few trades → likely overfitting
- PF just above 1.0 → may not survive real-world slippage

### Total Net Profit
**Definition:** Final Balance - Initial Balance

**Interpretation:**
- Absolute profit doesn't mean much without context
- Compare to initial deposit as percentage return
- Consider the time period (annualize if needed)

### Expected Payoff
**Definition:** Net Profit / Total Trades

**Interpretation:**
- Average profit per trade
- Should exceed typical spread + commission
- Negative = losing strategy

## Risk Metrics

### Maximum Drawdown
**Definition:** Largest peak-to-trough decline in equity

**Types:**
- **Absolute:** Actual currency loss
- **Relative (%):** Percentage from peak

**Interpretation:**
- <15%: Low risk
- 15-25%: Moderate risk
- 25-40%: High risk
- >40%: Very high risk (consider reducing)

**Formula:**
```
Max Drawdown = Max(Peak - Trough) for all peaks/troughs
DD% = (Max Drawdown / Peak Equity) * 100
```

### Recovery Factor
**Definition:** Net Profit / Maximum Drawdown

**Interpretation:**
- RF < 1: Haven't recovered from worst drawdown
- RF 1-2: Acceptable
- RF > 2: Good risk-adjusted returns
- RF > 3: Excellent

**Meaning:**
- RF = 2 means you earned 2x your worst drawdown
- Higher RF = faster recovery from losses

## Trade Quality Metrics

### Win Rate
**Definition:** Winning Trades / Total Trades * 100

**Interpretation:**
- Win rate alone is misleading
- Must consider risk:reward ratio
- A 30% win rate can be profitable with 3:1 R:R
- A 70% win rate can lose money with 0.3:1 R:R

**The Win Rate / PF Relationship:**
| Win Rate | Required Avg Win:Loss | Typical PF |
|----------|----------------------|------------|
| 30% | 2.5:1 | 1.07 |
| 40% | 1.5:1 | 1.00 |
| 50% | 1:1 | 1.00 |
| 60% | 0.67:1 | 1.00 |
| 70% | 0.43:1 | 1.00 |

### Total Trades
**Definition:** Number of completed trades (round trips)

**Interpretation:**
- <30: Too few for statistical significance
- 30-100: Marginally significant
- 100-500: Good sample size
- >500: Statistically robust

**Rule of thumb:**
- Minimum 30 trades to draw any conclusions
- Prefer 100+ for optimization results
- More trades = more confidence

## Advanced Metrics

### Sharpe Ratio
**Definition:** (Average Return - Risk-Free Rate) / Standard Deviation

**Interpretation:**
- <0: Loses money
- 0-0.5: Poor
- 0.5-1.0: Acceptable
- 1.0-2.0: Good
- >2.0: Excellent

**MT5 Calculation:**
Uses trade-by-trade returns, not daily returns

### Z-Score
**Definition:** Statistical measure of trade dependency

**Interpretation:**
- Near 0: Trades are independent (random)
- Positive: Wins tend to follow wins (trend)
- Negative: Wins tend to follow losses (mean-reversion)

**Percentage:** Probability that this pattern isn't random

### AHPR (Average Holding Period Return)
**Definition:** Average return per trade as percentage

### GHPR (Geometric Holding Period Return)
**Definition:** Compound average return per trade

**GHPR vs AHPR:**
- GHPR < AHPR is normal (variance drag)
- Large gap indicates high volatility in returns
- GHPR better represents actual compounding

### LR Correlation
**Definition:** Correlation of equity curve with linear regression line

**Interpretation:**
- Near 1.0: Smooth, consistent equity growth
- Near 0: Erratic, unpredictable
- Negative: Declining equity curve

### LR Standard Error
**Definition:** Average deviation from the regression line

**Interpretation:**
- Lower = smoother equity curve
- High = choppy, unreliable results

## Metric Combinations

### Quality Score Calculation
```python
score = (
    profit_factor * 20 +
    win_rate * 0.1 +
    recovery_factor * 15 +
    sharpe_ratio * 5 +
    (100 - max_drawdown_pct) * 0.2 +
    min(total_trades, 500) * 0.01
)
```

### Red Flags Matrix
| Condition | Warning |
|-----------|---------|
| PF > 5, Trades < 50 | Likely overfitting |
| DD > 50% | Strategy is too risky |
| Win Rate > 80%, PF < 1.5 | Small wins, large losses |
| Win Rate < 30%, PF > 2 | May be hard to follow psychologically |
| Sharpe < 0, PF > 1 | Inconsistent results |
| Recovery Factor < 0.5 | Takes too long to recover |

### Green Flags Matrix
| Condition | Indicates |
|-----------|-----------|
| PF 1.5-3, Trades > 100 | Robust strategy |
| DD < 20%, RF > 2 | Good risk management |
| Win Rate 45-55%, PF > 1.5 | Balanced R:R |
| Sharpe > 1 | Consistent returns |
| Monte Carlo Conf > 70% | Robust to sequence |
