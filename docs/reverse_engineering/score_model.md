# Scoring Models

This document describes the three scoring models used in the Astock system. Each model
evaluates a different aspect of a stock's technical setup and produces a 0-100 score and
a letter (or named) grade.

---

## 1. score_momentum_core() — 8-Factor Momentum Score

**File:** `/home/wade/workspace/ai/Astock/core/strategy.py`, line 218  
**Signature:** `score_momentum_core(bars: list[dict], params: dict | None = None) -> dict`

A general-purpose momentum scoring engine that evaluates a single stock's daily bar
data across eight factors. All weights are configurable through the `params` dict.

### Default Weights

| Factor | Default Weight | Config Key | Description |
|---|---|---|---|
| Volume ratio | 25 | `volume` | VR-based volume scoring |
| Distance from 10d high | 20 | `dh` | How close close is to 10-day high |
| MA alignment | 20 | `ma` | Moving average stacking quality |
| RSI | 15 | `rsi` | RSI zone scoring |
| Daily change | 15 | `chg` | Single-day price change |
| Volatility bonus | 5 | `vol_bonus` | Daily range bonus |
| 20d new high bonus | 5 | `new_high_bonus` | Near 20-day high bonus |
| Pullback bonus | 10 | `pullback_bonus` | Pullback-in-volume setup bonus |

### Hard Filters (pre-score)

A stock is rejected immediately (score=0, grade="D") if any of the following fail:

| Filter | Parameter Key | Default Threshold |
|---|---|---|
| Volume ratio | `min_vr` | VR >= 0.8 |
| RSI | `min_rs` | RSI >= 25 |
| Close vs MA20 | `ma_pct` | close >= ma20 * 0.95 |

### Trading Parameters (returned alongside score)

| Parameter | Key | Default |
|---|---|---|
| Target profit | `target_pct` | 8% |
| Stop loss | `stop_pct` | -2.8% |
| Hold days | `hold_days` | 3 |

### Factor Details

#### 1. Volume (0-25 points)

Compares last bar volume to the 20-bar simple moving average of volume.

| Condition | Pct of Weight | Points (at default weight 25) |
|---|---|---|
| VR > 3.0 | 100% | 25 |
| VR > 2.0 | 80% | 20 |
| VR > 1.5 | 60% | 15 |
| VR > 1.2 | 40% | 10 |
| VR > 1.0 | 24% | 6 |
| else | 12% | 3 |

#### 2. Distance from 10-Day High (0-20 points)

Calculated as `dh10 = (hi10 - close) / hi10 * 100` where `hi10` is the highest high of
the last 10 bars.

| Condition | Pct of Weight | Points (at default weight 20) |
|---|---|---|
| dh10 < 1% | 100% | 20 |
| dh10 < 3% | 80% | 16 |
| dh10 < 5% | 60% | 12 |
| dh10 < 8% | 35% | 7 |
| dh10 < 12% | 20% | 4 |
| else | 0% | 0 (no points added) |

#### 3. MA Alignment (0-20 points)

Evaluates the stacking relationship of the 5-, 10-, and 20-bar simple moving averages.

| Condition | Pct of Weight | Points (at default weight 20) | Named Pattern |
|---|---|---|---|
| close > ma5 > ma10 > ma20 | 100% | 20 | `trend` |
| close > ma5 > ma20 | 70% | 14 | -- |
| close > ma20 | 50% | 10 | -- |
| else | 10% | 2 | -- |

#### 4. RSI (0-15 points)

| Condition | Pct of Weight | Points (at default weight 15) |
|---|---|---|
| 45 <= RSI <= 65 | 100% | 15 |
| 65 < RSI <= 75 | 67% | 10 (10.05 floored) |
| 35 <= RSI < 45 | 53% | 7 (7.95 floored) |
| RSI > 75 | 27% | 4 (4.05 floored) |
| else (RSI < 35) | 13% | 1 (1.95 floored) |

#### 5. Daily Change (0-15 points)

Based on the last bar's `change_pct`. When change > 5 the pattern name is set to `ignition`.

| Condition | Pct of Weight | Points (at default weight 15) | Named Pattern |
|---|---|---|---|
| chg > 7% | 100% | 15 | `ignition` |
| chg > 5% | 87% | 13 (13.05 floored) | `ignition` |
| chg > 3% | 67% | 10 (10.05 floored) | -- |
| chg > 1.5% | 47% | 7 (7.05 floored) | -- |
| chg > 0.5% | 27% | 4 (4.05 floored) | -- |
| else | 7% | 1 (1.05 floored) | -- |

#### 6. Volatility Bonus (0-5 points)

Daily range = `(high - low) / low * 100`.

| Condition | Pct of Weight | Points (at default weight 5) |
|---|---|---|
| range > 5% | 100% | 5 |
| range > 3% | 60% | 3 |
| else | 0% | 0 |

#### 7. 20-Day New High Bonus (0-5 points)

If the 10-day high is within 99% of the 20-day high, the stock is near a new high. The
pattern name is set to `breakout`.

| Condition | Points |
|---|---|
| hi10 >= hi20 * 0.99 | +5 (and name = `breakout`) |
| else | +0 |

#### 8. Pullback Bonus (0-10 points)

Evaluates the last 10 bars (excluding the current bar). If the maximum single-bar change
within that window exceeds 5% and the current VR is below 0.9, the setup is a pullback.
The pattern name is set to `pullback`.

| Condition | Points |
|---|---|
| max(chg in bars[-10:-1]) > 5 AND vr < 0.9 | +10 (and name = `pullback`) |
| else | +0 |

### Score Capping & Grade

```
final_score = min(raw_score, 100)
```

| Range | Grade |
|---|---|
| >= 65 | A |
| >= 50 | B |
| >= 35 | C |
| < 35 | D |

### Return Value

```python
{
    "score": int,          # 0-100
    "grade": str,          # "A" | "B" | "C" | "D"
    "name": str,           # "momentum" | "trend" | "ignition" | "breakout" | "pullback"
    "target_pct": float,   # e.g. 8.0
    "stop_pct": float,     # e.g. -2.8
    "hold_days": int,      # e.g. 3
    "atr_pct": float       # ATR as % of close
}
```

---

## 2. compute_signal_score() — Chanlun Signal Score

**File:** `/home/wade/workspace/ai/Astock/scripts/backtest_engine.py`, line 151  
**Signature:** `compute_signal_score(buy_point, weekly_trend, daily_trend, vol_ratio, rsi, sentiment_mult) -> dict`

Scores a chanlun (缠论)-based buy signal by evaluating five confluence factors.
The total score is the sum of all five components (max 100).

### Component Breakdown

#### 1. Trend Alignment (30 points)

Evaluates the combination of weekly and daily trend direction.

| Weekly Trend | Daily Trend | Points | Reason |
|---|---|---|---|
| `uptrend` | `uptrend` | 30 | 周线+日线双多头 |
| `uptrend` | `range` | 24 | 周线多头+日线震荡 |
| `range` | `uptrend` | 22 | 周线震荡+日线多头 |
| `range` | `range` | 18 | 双震荡 |
| `uptrend` or `range` | `downtrend` | 10 | 周线可+日线下行 |
| `downtrend` | `uptrend` or `range` | 6 | 周线下行+日线可(逆势) |
| `downtrend` | `downtrong` | 2 | 双下行(规避) |

#### 2. Buy Point Quality (25 points)

Maps the chanlun buy point type to a score.

| Buy Point | Points |
|---|---|
| 三买 (third buy) | 25 |
| 一买 (first buy) | 18 |
| 二买 (second buy) | 14 |
| Any other (breakout, default) | 8 |

Note: The buy point is resolved by exact string match on the `buy_point` argument; any
value not in `{"三买", "一买", "二买"}` receives the default 8 points.

#### 3. Volume Confirmation (15 points)

| Condition (vol_ratio) | Points | Label |
|---|---|---|
| >= 2.0 | 15 | 放量 |
| >= 1.5 | 12 | 放量 |
| >= 1.0 | 8 | 平量 |
| >= 0.7 | 5 | 缩量 |
| < 0.7 | 2 | 地量 |

#### 4. RSI Zone (15 points)

| Condition | Points | Label |
|---|---|---|
| 30 <= RSI <= 45 | 15 | 理想 |
| 45 < RSI <= 55 | 12 | 中性 |
| 20 <= RSI < 30 | 10 | 超卖边缘 |
| 55 < RSI <= 65 | 8 | 偏高 |
| RSI < 20 | 5 | 深度超卖 |
| RSI > 65 | 2 | 超买 |

#### 5. Sentiment Phase (15 points)

Maps the market sentiment multiplier (regime multiplier) to a score.

| Condition | Points |
|---|---|
| sentiment_mult >= 0.7 | 15 |
| sentiment_mult >= 0.4 | 10 |
| sentiment_mult >= 0.2 | 5 |
| else | 1 |

### Grade Boundaries

| Range | Grade |
|---|---|
| >= 75 | A |
| >= 55 | B |
| >= 35 | C |
| < 35 | D |

### Return Value

```python
{
    "total": int,
    "grade": str,           # "A" | "B" | "C" | "D"
    "components": {
        "trend_alignment": int,
        "buy_point_quality": int,
        "volume": int,
        "rsi": int,
        "sentiment": int
    },
    "reasons": list[str]    # Human-readable Chinese labels
}
```

---

## 3. leader_score() — Limit-Up Leader Score

**File:** `/home/wade/workspace/ai/Astock/core/chanlun_engine.py`, line 226  
**Signature:** `leader_score(row, sector_count=0, sector_rank=99, continuity_days=0) -> dict`

Scores a stock that has recently hit limit-up (涨停) to assess whether it qualifies as
a sector leader. The score is built from six additive components minus risk penalties.

### Components

#### Streak (0-30 points)

Number of consecutive limit-up days (`limit_up_days` or `streak` field in the row).

```
points = min(30, streak * 10)
```

| Streak | Points |
|---|---|
| 1 board | 10 |
| 2 boards | 20 |
| 3+ boards | 30 (capped) |

#### Amount (0-20 points)

Trading amount in yuan.

```
points = min(20, amount / 50_000_000 * 4)
```

| Amount | Points |
|---|---|
| >= 250M | 20 (capped) |
| 100M | 8 |
| 50M | 4 |
| < 50M | < 4 (see risk penalty) |

#### Sector Breadth (0-15 points)

Number of stocks in the same sector that also hit limit-up.

```
points = min(15, sector_count * 3)
```

| Sector Count | Points |
|---|---|
| 5+ | 15 (capped) |
| 3 | 9 |
| 1 | 3 |

#### Sector Rank (0 or 8 or 15 points)

Rank of the stock's sector among all sectors.

| Sector Rank | Points |
|---|---|
| <= 3 | 15 |
| <= 10 | 8 |
| > 10 | 0 |

#### Continuity (0-10 points)

Number of consecutive days the sector theme has persisted.

```
points = min(10, continuity_days * 3)
```

| Continuity Days | Points |
|---|---|
| 4+ days | 10 (capped) |
| 2 days | 6 |
| 1 day | 3 |

#### Turnover Quality (0 or 4 or 10 points)

Based on the stock's turnover rate (%).

| Turnover Rate | Points |
|---|---|
| 3% <= turnover <= 18% | 10 |
| turnover > 0% (outside ideal range) | 4 |
| turnover == 0% | 0 |

### Risk Penalties

Penalties are applied **after** the additive components are summed. Each risk
also records a label in the `leader_risks` list.

| Condition | Penalty | Risk Label |
|---|---|---|
| turnover > 25% | -12 | `excessive_turnover` |
| streak == 1 AND sector_count < 3 | -10 | `one_day_isolated` |
| amount < 50,000,000 | -10 | `low_liquidity` |

### Score Capping

```
final_score = max(0, min(100, round(raw_score, 2)))
```

### Classification (Grade)

| Range | Classification |
|---|---|
| >= 70 | `main_uptrend_leader` |
| >= 55 | `strong_watch` |
| < 55 | `observation_only` |

### Return Value

```python
{
    "leader_score": float,      # 0-100
    "leader_class": str,        # "main_uptrend_leader" | "strong_watch" | "observation_only"
    "score_components": {
        "streak": int,          # min(30, boards * 10)
        "amount": int,          # min(20, amount / 50M * 4)
        "breadth": int,         # min(15, sector_count * 3)
        "sector_rank": int,     # 0 | 8 | 15
        "continuity": int,      # min(10, days * 3)
        "turnover_quality": int # 0 | 4 | 10
    },
    "leader_risks": list[str]   # e.g. ["excessive_turnover", "low_liquidity"]
}
```

### Worked Example

A stock with:
- 2 limit-up boards (`streak=2`): 20 pts
- Amount = 120M: `min(20, 120M/50M*4) = min(20, 9.6)` = 9.6 pts
- Sector has 3 limit-up stocks: `min(15, 3*3)` = 9 pts
- Sector rank = 2: 15 pts
- Continuity = 1 day: `min(10, 1*3)` = 3 pts
- Turnover = 8%: 10 pts
- No risk penalties triggered

Raw total: 20 + 9.6 + 9 + 15 + 3 + 10 = 66.6  
Final: `round(66.6, 2)` = 66.6  
Classification: `strong_watch` (55 <= 66.6 < 70)

---

## Summary Comparison

| Model | Domain | File | Line | Max Score | Grades |
|---|---|---|---|---|---|
| `score_momentum_core` | General momentum | `core/strategy.py` | 218 | 100 (capped) | A/B/C/D |
| `compute_signal_score` | Chanlun signals | `scripts/backtest_engine.py` | 151 | 100 | A/B/C/D |
| `leader_score` | Limit-up leaders | `core/chanlun_engine.py` | 226 | 100 (capped) | main_uptrend_leader / strong_watch / observation_only |
