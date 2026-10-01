# Strategy Learning and Circuit-Breaker Contract

Use this contract when auditing or modifying the daily strategy-learning loop, outcome settlement, cooldown state, or execution-time breaker.

## 1. Separate three different questions

1. **Signal research quality** — may learn from real and shadow outcomes for statistical analysis.
2. **Entry-strategy capital protection** — may be driven only by real BUY outcomes that exposed capital.
3. **Exit quality** — SELL outcomes measure timing of an exit; they must not freeze the originating entry strategy or block future defensive exits.

Do not feed all three into one undifferentiated `catalyst_type` history.

## 2. MAE sign and unit contract

The outcome ledger records maximum adverse excursion as a negative return, for example `-11.81` for `-11.81%`.

- Catastrophic MAE comparison: `mae <= -threshold`, never `mae >= threshold`.
- Normalize decimal returns before comparison: `-0.1181 -> -11.81` when the source uses fractional returns.
- Use the same normalization in statistics, P0 action generation, parameter-state migration, and the physical breaker.
- When selecting the worst record, compare the worse of close PnL and MAE. Sorting only by close PnL misses a deep intraday collapse that closes flat.

Recommended entry-risk value:

```python
close_pnl = pct_value(outcome.get("pnl_pct"))
mae = pct_value(outcome.get("mae"))
effective_pnl = min(close_pnl, mae)
```

Retain all three fields for auditability: `pnl_pct` (effective risk), `close_pnl_pct`, and `mae`.

## 3. Physical breaker ingestion boundary

The execution breaker must ingest only:

```text
record_type == candidate_outcome
AND direction == buy
```

It must exclude:

- `shadow_outcome` — useful for research, but no real capital was exposed.
- SELL outcomes — these evaluate exit quality, not the entry strategy.
- Unsettled candidates and execution events.

During full-state recalculation, ignore legacy non-BUY history so old polluted SELL records cannot keep a strategy frozen.

## 4. Cooldown directionality

A strategy cooldown or blacklist means **no new risk exposure**. Therefore:

- BUY: enforce catalyst enablement, cooldown, blacklist, and breaker state.
- SELL: bypass entry-strategy cooldown and blacklist so stop-loss, take-profit, and emergency liquidation remain available.

The caller must pass direction into the catalyst gate. A direction-blind `is_catalyst_enabled(catalyst_type)` is unsafe.

## 5. Idempotent sync and historical backfill

Prefer `candidate_id` as the durable identity. Fallback keys should include timestamp, symbol, catalyst, and direction.

A pure “already seen → skip” rule is insufficient after the schema evolves. Existing rows may lack MAE or normalized close PnL. Sync must support an **in-place upgrade**:

1. Index existing history by `candidate_id`.
2. If a matching outcome contains missing/richer fields, update the row rather than append a duplicate.
3. Rewrite the JSONL atomically with tmp + replace.
4. Append only genuinely new candidates.
5. Recalculate breaker state after inserts or upgrades.

This prevents an old flat-close record from permanently hiding a later-discovered `MAE=-11.81%`.

## 6. Required regression cases

Write tests first and verify RED before implementation:

1. Negative MAE triggers catastrophic action even when close PnL is zero.
2. Among equal close PnL records, the largest adverse MAE is selected as worst.
3. Decimal MAE normalizes consistently in both evolution audit and breaker sync.
4. Disabled/cooling strategy blocks BUY but permits SELL.
5. Full-state recalculation ignores legacy SELL history.
6. Sync imports real BUY outcome and skips real SELL and shadow outcomes.
7. Flat close plus deep MAE stores the deep adverse value as effective risk.
8. Existing candidate history is upgraded in place without duplication.

## 7. Stateful test isolation

Tests that call production gates must not depend on the live breaker file. A legitimately frozen production strategy will make an old “should allow BUY” unit test fail.

- Unit tests: monkeypatch `check_strategy` or redirect breaker paths to a temporary fixture.
- Integration tests: run separately against the live state and assert that the current production decision is enforced.
- Never clear or weaken the live breaker merely to make a unit test green.

## 8. Before/After evidence

A completed fix must show all of:

- Original outcome row (`close_pnl`, `mae`, direction, record type).
- Old strategy state and the incorrect decision.
- Updated history row after backfill.
- New breaker state (`is_blocked`, reason, expiry).
- Proof SELL exits remain allowed.
- Focused regression results plus related-suite results.
- Independent AGY review for logic changes, followed by a final re-review after P2 findings are closed.
