# Resume-State Verification

Use this checklist after context compression, session resume, or a user handoff that lists completed and incomplete work.

## Evidence-first sequence

1. Resolve the live workspace: `pwd`, `HERMES_HOME`, active profile, and git branch.
2. Check every claimed path with the file API. Do not assume `~/.hermes` is the active home when profiles or an alternate environment may be in use.
3. Inspect the actual cron registry and scheduler status. Reconcile IDs, enabled state, schedule, last run, and script path.
4. Re-run syntax checks and focused tests before reporting implementation status.
5. For side effects, verify the artifact: stat/read the file, inspect the cron record, and confirm git diff/commit/push output.
6. If a tool is interrupted, timed out, or returns partial output, label the result `unverified` and stop short of success claims. Retry with one minimal diagnostic or a different tool, then report the blocker if it persists.

## Anti-patterns

- Treating a compressed summary as current filesystem state.
- Recreating files because an assumed path was missing.
- Reporting a planned change as implemented.
- Reporting a cron trigger request as a successful job run without checking its output artifact.
- Claiming tests passed from `py_compile` alone; compilation is only a syntax check.

## Suggested evidence table

| Claim | Required evidence |
|---|---|
| File exists | File read/stat at the live path |
| Behavior works | Focused test or controlled run output |
| Cron is configured | `hermes cron list --all` plus registry inspection |
| Cron completed | Run record plus expected artifact |
| Commit pushed | Git commit and remote verification |
