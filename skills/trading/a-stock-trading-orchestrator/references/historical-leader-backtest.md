# Historical Leader Backtest Reference

## Purpose

Use this workflow when a user asks: "At what point would the autonomous system have alerted me to buy this leader?" The question is a historical signal-quality test, not a current quote recommendation.

## Required output

For each historical event, record:

| Field | Meaning |
|---|---|
| decision_time | Last timestamp available when the decision was made |
| event_class | observe / first_entry / add_on / hold_only / chase_reject / risk_exit |
| price_or_range | Actual bar price or executable range, not a hindsight target |
| chan_evidence | Confirmed structural evidence and source bars |
| volume_evidence | Relative expansion/contraction and whether it confirms price |
| sector_news_evidence | Sector breadth/resonance and contemporaneous news/announcement evidence |
| execution | simulated fill, unavailable, limit-up queue, or rejected |
| invalidation | Structural condition that would cancel the signal |
| hindsight_status | available_at_time or hindsight_only |

## Point-in-time sequence

1. Pull enough historical intraday data to include the full setup. For a leader, default to 100 30-minute bars and extend the range if the requested start date is not covered.
2. Split the data at each decision timestamp. Indicators, Chan structure, sector evidence, news, and risk status must use only data at or before that timestamp.
3. Mark the initial range as `observe` until a platform breakout and pullback/retest are confirmed. A low price alone is not a buy signal.
4. Mark `first_entry` only when the platform breaks, the retest holds, and price/volume/sector conditions agree. Record a price range and a structural invalidation level.
5. Mark later consecutive limit-up bars as `hold_only` or `add_on` according to the strategy. A newly discovered leader after several locked limit-up bars is `chase_reject` unless the strategy explicitly supports a tested continuation entry.
6. At the first high-volume divergence, failed breakout, abnormal turnover, or contemporaneous risk announcement, emit `risk_exit`/de-risking evidence. Do not reinterpret this as a new entry.
7. Report the earliest valid first-entry signal and compare it with later prices only as an outcome measurement.

## Anti-lookahead rules

- Do not use the eventual high, later announcement, later leader ranking, or later closing price to create an earlier signal.
- A news search performed today is not proof that the same news was available at the historical decision time. Label retrospective-only news `hindsight_only` unless its publication timestamp is established.
- A daily limit-up table can identify a candidate, but it cannot replace the intraday structure required for the first-entry decision.
- If the historical feed lacks a bar, sector snapshot, or execution state, mark the result `observation_only` or `execution_unverified`; do not fill the gap with assumptions.

## Example interpretation

For a stock that ranges near 7.00, breaks the range and holds a 7.10-7.20 retest before its first limit-up, the useful historical conclusion is: `first_entry` near the confirmed breakout/retest, with a stop below the invalidated platform. The later 8.71, 9.58, and 10.54 limit-up prices are outcome/hold-management data, not fresh first-buy signals.

## Minimum verification

- Confirm the K-line count, timestamps, and period.
- Preserve raw source evidence or a compact fixture.
- Verify that the candidate schema can be consumed by the autonomous trade gate.
- Run the relevant pipeline/backtest tests and check for real order side effects.
