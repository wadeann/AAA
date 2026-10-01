# Deterministic Trade Pipeline Verification

Use this checklist when auditing an A-share autonomous trading pipeline.

## Required separation

- Research and close review produce evidence, candidates, reports, and feedback only.
- One deterministic no-agent trade gate consumes validated candidates.
- No prompt-only cron may call execution tools directly.
- Duplicate autonomous-execution jobs must be paused or removed.

## Candidate ledger contract

`candidate` is a forward-looking research record. It must include a stable `candidate_id`, symbol, direction, price, quantity, confidence, thesis, entry rule, and evidence-gate fields.

Use separate record types:

- `candidate_event`: filtered, risk_rejected, dry_run, submitted, failed, or execution_skipped.
- `candidate_outcome`: only after forward prices or actual trade evidence exists; carries outcome, MFE, MAE, B-wave and root-cause fields.
- `position_review`: existing holdings only; never count as candidate performance.

Unsettled candidates belong in the close report as `pending`, with null MFE/MAE/B-wave values. Do not convert missing data into a loss or flat result.

## Execution state machine

1. Load and deduplicate candidates by `candidate_id`.
2. Apply research gates before risk: Chan buy point, volume, sector confirmation, fundamental evidence, realtime evidence, confidence and valid order fields.
3. Normalize a pending TradeIntent. Do not add `intent_id` or claim approval locally.
4. Call `risk_batch_check` and reject the whole batch if the response count does not match the input count.
5. Treat `approved=true` as `approval_status=approved` when the server omits the enum; never overwrite an explicit rejection.
6. In production mode, require a valid `intent_id`, register if needed, place exactly one order, query orders for reconciliation, and archive the complete intent.
7. In dry-run, archive the intent as dry-run and never call execution.
8. Persist every non-performance state as `candidate_event`; never include those rows in win-rate statistics.

## Verification layers

### Standard-library mock tests

Cover: all research gates, risk rejection, approved status normalization, missing intent ID, risk response count mismatch, registration failure, order failure, order reconciliation, deduplication, dry-run, and idempotent intent archive naming.

### Real MCP checks

Safe checks include:

- `risk_batch_check` with an empty list.
- A known non-trading-day rejection path.
- Read-only orders, trades, positions, balances, and trading-session queries.
- Confirm no pending order or trade was created.

Do not use a fabricated approved intent to reach production `place_order` merely to test the path. Keep the explicit execution flag disabled unless the user authorizes a controlled trade.

## Scheduler audit

Validate both `cron/jobs.json` and `hermes cron list --all`. Check unique IDs, enabled state, schedule, `script`, `no_agent`, `paused_at`, and last-run timestamps. A scheduler-level `ok` is insufficient: run the script directly and verify exit code, report path, JSONL parseability, and MCP output.

The watchdog must fail closed when the authoritative trading-session response is missing or not explicitly true. It must compare `last_run_at` against the scheduled target, persist one recovery attempt per date/job, and retain only bounded state history.
