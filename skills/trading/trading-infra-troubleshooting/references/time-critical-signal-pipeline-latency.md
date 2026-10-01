# Time-Critical Signal Pipeline Latency

Use this when a valid A-share signal, push, or order appears minutes late even though the broker and MCP services are healthy.

## Reconstruct the timeline from durable evidence

Do not infer timing from the final candidate row alone. Correlate four clocks in CST:

1. Orchestrator phase log: phase start/end, child timeout, gate invocation.
2. Scanner output: score completion, candidate write, notification result.
3. Candidate JSONL: `created_at`, approval/rejection events, `executed` event.
4. Broker orders: submitted/filled timestamp, symbol, quantity, price.

Normalize UTC timestamps before comparison. Distinguish:

- detection latency: market event → scanner recognition;
- publication latency: recognition → candidate/push;
- queue latency: candidate → executor start;
- broker latency: executor start → fill.

This prevents blaming the broker when the scanner actually timed out upstream.

## High-frequency root cause pattern

A parent orchestrator launches a child scanner with a strict timeout. The scanner evaluates up to N independent stocks serially, and each stock performs several local MCP calls. The child is killed before it writes candidates. A later standalone cron run succeeds, creating the illusion of a slow signal.

Evidence signature:

- parent log says child timed out;
- early trade gate reports no signal;
- standalone scanner later writes and pushes the same names;
- executor and broker complete quickly after candidate creation.

## Durable repair pattern

1. Parallelize only independent per-symbol evaluation with a bounded worker pool.
2. Preserve deterministic input order (`executor.map` or equivalent) so downstream clash/ranking logic is unchanged.
3. Keep all market, chip, fund-flow, sentiment, position, and iron-rule gates intact.
4. After a successful high-priority scan, invoke the executor immediately in a separate process. Do not wait for the periodic polling cron.
5. Increase the parent timeout only as headroom; do not use timeout inflation as the sole fix.
6. Remove redundant later new-position scans. Keep later jobs for leaderboard refresh and held-position defense only.
7. Ensure the scanner has an explicit morning entry window so manual or delayed afternoon runs cannot inject chase orders.

## Verification

Run all of these before declaring success:

- targeted concurrency test with synthetic per-symbol delay;
- closed-loop test asserting `scan → executor` call order;
- timeout test asserting executor is not called after scanner failure;
- afternoon-window test asserting zero new buy candidates;
- `py_compile` and cron JSON validation;
- live cron listing to confirm the scheduler loaded the new expression;
- final system health check.

Report Before/After numerically:

- old real phase runtime and timeout;
- synthetic serial baseline vs bounded-parallel runtime and speedup;
- old candidate-to-fill delay;
- new expected path, identifying which polling wait was eliminated.

## Pitfalls

- Candidate dedup rewrites may preserve or replace timestamps; use scanner output and event records as additional clocks.
- A batch executor with `ready[:BATCH_SIZE]` can delay lower-ranked buys behind sells or other candidates. Immediate invocation removes polling delay but not queue-order delay; inspect batch ordering separately.
- Full tests can fail because live strategy cooldown/blacklist state is intentionally active. Separate environment-state failures from regression tests, but never hide them; run focused tests for the changed path and report both results.
- Repeated afternoon scanner jobs are not harmless merely because dedup exists: they can spam alerts and become dangerous if a window guard regresses.
