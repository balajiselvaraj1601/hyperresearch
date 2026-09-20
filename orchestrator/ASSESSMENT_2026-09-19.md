# Hyperresearch systemic assessment, 2026-09-19

Scope: the two tmux/cca lanes on mimo (`hpr-lane-a` → `litellm-cost-perf-ops-506ad8`,
`hpr-lane-b` → `ai-productivity-tools-096ea7`), the earlier subagent attempt, and the
orchestrating session. Evidence: lane transcripts
(`~/.claude/projects/-home-monster-agentspace-hyperresearch/{1dde0084,35daa070}*.jsonl`),
`orchestrator/logs/*`, both run vaults, `/tmp/agentspace/hyperresearch-parallel-tracker.csv`,
and `git show 0c9db9a`.

## Findings and fixes

| # | Finding | Evidence | Cause | Fix (this pass) |
|---|---|---|---|---|
| 1 | Step contracts were executed **raw**: 65 `<< p.x >>` placeholders, `$HPR`, `<vault_tag>` and relative paths never rendered. Nothing has rendered them since the installer was retired in `0c9db9a`. | 16 tool results in the two transcripts contain literal `<< p.`; lane B tried `from hyperresearch.core.profiles import PROFILES` twice (ImportError) to recover the numbers; lane A guessed `run step-done` (exit 2). | CLI gap | `hyperresearch run contract <tag> <N>` (new `core/contracts.py`). Runner agent, pipeline skill, 18 wrappers, entry skill and `launch_lane.sh` now route through it. |
| 2 | The 16 specialised worker bodies (fetcher with claims extraction, four critics, patcher, synthesizer, ...) were deleted with the fleet; every spawn became a bare `agent_medium` with a 3-line header plus shim. | Zero `claims-*.json` in both vaults → steps 3 and 9 skipped in both runs; instruction critic returned 0 findings (lane A, both passes); width critic missing (lane B); lane B WebFetched 52 source pages (the old fetcher brief forbade it). | skill-body | 16 role briefs recovered from `0c9db9a^` into `src/hyperresearch/skills/roles/`; every spawn template ends with `ROLE BRIEF: ... run contract <tag> --role <r>`; spawn contract items 5 (brief) and 6 (absolute paths) added to `hyperresearch.md`. Depth investigator brief switched from nested Task spawns to direct `$HPR fetch` (roster leaves cannot spawn). |
| 3 | Re-running a shipped run: `run step --status pending` left `status: done` and a stale `verify.passed: true`; the lane then flipped steps 13-16 `done` in 1.1 s with a stub patch log (`applied: []`), an empty polish log and `[]` cite-check. Three critical depth findings (guardrails overstated, tool-level ACL, streaming crash isolation) were never applied and the flagged guardrail sentence shipped. `run verify` passed on file presence. | `run.json` step timestamps 03:16:29–31; `patch-log.json` skip reason "v2 run — critic findings addressed in synthesis pass"; report line 124. | core (state machine + weak gate) | `set_step` reopens a done run; new verify check `critical-findings-resolved` (criticals must be applied or skipped by name). Positive control: `run verify litellm-cost-perf-ops-506ad8` now FAILS (4 criticals, 0 dispositions); lane B still passes. |
| 4 | Seven run artifacts written outside the run dir (repo root, `agentspace/output/`) by subagents resolving relative paths against their own cwd. | tracker rows 8, 18 | skill-body | Rendered contracts carry absolute paths; spawn contract item 6. |
| 5 | Spend counters never move: `sources_fetched: 0` after 46 fetches, `agents_spawned: 0` after 55 spawns. No contract calls `run spend`. | both `run.json` | core | `fetch --tag <run>` auto-credits `sources_fetched`/`notes_written`. `agents_spawned` still manual (see open items). |
| 6 | Vault DB opened with WAL and the 5 s default timeout, no `busy_timeout`; two lanes shared it. No lock errors this time. | `core/db.py:230` | latent | `timeout=30` + `PRAGMA busy_timeout=30000`. |
| 7 | Zero prompt-cache hits on mimo: 120 M input tokens resent across ~650 turns. | usage audit, tracker rows 13-15 | environment (gateway) | Not a repo issue. Log only. |
| 8 | Transient gateway 400 (`no fallback model group for mimo`) idled lane A for 55 min. | tracker row 17 | environment | Log only; a stall watchdog in `launch_lane.sh` is an open item. |
| 9 | `research_root_guard` false positive on `hyperresearch/` (regex matched bare `research/`). | tracker rows 12, 23 | workspace hook | Fixed earlier this session in agentspace (`.claude/hooks/guards/research_root_guard.py`, poison-pill tested). |
| 10 | Installed CLI is a non-editable `uv tool` copy; repo edits are invisible until reinstall. | `direct_url.json` | environment | Reinstalled with `uv tool install --reinstall .`; noted in Next. |

## What worked

- Mimo as the top-level session model produced real content when given room (step 8 corpus critic found a primary CVE source; lane B's adversarial section steelmans five counterarguments). The earlier placeholder output came from the 8k Task-tool cap, not the model.
- `run verify`'s existing checks (headings, density, quote integrity, retracted citations) held. The gap was what they did not measure.
- The local pipeline skill's "verify the artifact, not the manifest" rule caught the step-7 placeholder on re-check.

## Verification

- `uv run --extra dev pytest tests`: all pass except `tests/test_mcp/test_update_note.py` (2 failures, present at HEAD before this work).
- New tests: `tests/test_core/test_contracts.py` (25), `TestCriticalFindingsGate` (3) and `TestReopenShippedRun` (1) in `test_verification.py`. The four F3 tests were confirmed to FAIL against HEAD `runs.py` before the fix.
- Golden snapshots regenerated for the deliberate spawn-template change; the deviation is logged in `test_prompt_golden.py`'s docstring.
- Live: `hyperresearch run contract litellm-cost-perf-ops-506ad8 2` renders with 0 leftover placeholders; `--role fetcher` carries the claims-extraction schema.

## Follow-up (2026-09-19 session closeout, Cursor)

Completed after the Claude session stalled on Anthropic classifier rate limits:

- Output layout shipped: `output/reports/<tag>/`, `output/notes/<tag>/`. Migrated
  138 flat notes (64 litellm, 74 productivity) and both final reports. CLI
  reinstalled; `run contract` / `run verify` both point at the new report path.
- Fixed `test_verification.py` path rewrite bug (`Vault / "output"` →
  `Vault.root`, plus `mkdir` for nested reports). Contracts + verification
  tests green; full suite minus `test_mcp` green.

## Open items (not done)

1. Lane A (#52): the four criticals are dispositioned as named skips in `patch-log.json` (user decision 2026-09-19 04:37 UTC) and the run re-finished, verify passed. The report text itself is unchanged; the guardrail overstatement at line 124 stands, recorded in the skip reason.
2. `agents_spawned` needs an orchestrator-side `run spend --agents N` call per spawn wave, or an event hook; not wired.
3. `launch_lane.sh` has no stall watchdog (`possibly_stalled` from `run status` is available to poll).
4. `tests/test_mcp/test_update_note.py` fails at HEAD (note path under `output/notes` not created); unrelated, untouched.
5. Workspace `CLAUDE.md` Research Base block still says the runner "reads each step contract"; proposal filed in its Proposal section.
6. Prompt caching on the mimo route is 0 %; gateway-side question for LiteLLM (`cache_control` passthrough on `nvidia/nemotron-3-super-120b-a12b`).
7. `uv.lock` was generated by `uv run` during testing and trashed; `UV_FROZEN=1` in the environment requires `env -u UV_FROZEN` to run tests via uv.
