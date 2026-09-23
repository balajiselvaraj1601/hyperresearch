# Ecosystem recommendations from hyperresearch output audit, 2026-09-21

Source: audit of `hyperresearch/output/` (2 full-profile runs, 2 final reports,
~138 notes, 6 raw PDFs) cross-checked against `manage_environment/manage_litellm`
(272-setting checklist, verification suites) and `orchestrator/ASSESSMENT_2026-09-19.md`.
Prior analysis turn verified all claims against run manifests, critic findings,
patch logs, and the live gateway checklist. A background 5-surface workflow
synthesis may still add refs.

## P0 — cost

1. **Prompt-cache passthrough on the mimo route.** Assessment open item 6:
   0% cache hits, ~120M input tokens resent over ~650 lane turns. Gateway-side
   question for LiteLLM (`cache_control` passthrough on
   `nvidia/nemotron-3-super-120b-a12b`). Largest single $ lever; dwarfs all
   response-caching options.
2. **Per-harness virtual keys + budget caps + spend dashboard** (report §7).
   Ecosystem Phase 4 not started (no virtual keys). Note the caveat from
   comparisons tension 5: `max_parallel_requests` enforcement bug makes caps a
   soft ceiling until the fix is verified in the deployed release — budget caps
   (hard spend ceiling) carry the containment weight, not concurrency caps.

## P1 — performance / reliability

3. **Stall watchdog in `orchestrator/launch_lane.sh`** (assessment open item 3):
   poll `run status` `possibly_stalled`; a transient gateway 400 idled lane A
   55 min.
4. **Adopt scale-independent hygiene from report §§2/4/6**: simple-shuffle
   routing unless SLA-bound, `num_retries >= 3` with backoff+jitter, readiness
   probes decoupled from upstream health, streaming worker isolation, explicit
   per-model `request_timeout` (community values: 300s large / 120s min /
   never <90s streaming — missing from report per depth critic, add them).
5. **Budget callback/logging infra as separate capacity** (issue #12067) and
   run Redis/Valkey as a required shared dependency with circuit-breaker
   version floor >=1.82.0 whenever caching or multi-worker rate limits exist
   (comparisons tension 1).
6. **Validate client-side, never gateway-side**: 100% self-reported vs 92.07%
   client-observed success (tensions 2/3 convergence). All local capacity
   claims need Locust-style client instrumentation.

## P1 — output quality

7. **Vault hygiene**: remove `output/notes/test.txt`; add fetcher junk filter
   (bot-gated pages, "Skip to content" chrome, consent-banner near-dups) and
   content-hash dedup (`close-this-consent-banner*.md`, chrome-only note that
   forced a width width-skip).
8. **Populate `output/index/`** (empty; roadmap Phase 2 ranking has no runtime
   footprint) and triage `output/_inbox/`; clarify provenance of
   `output/notes/github/` (full report, no run dir).

## P1/P2 — assessment quality

9. **Annotate the 4 skipped criticals in the litellm report text**, esp. the
   guardrail overstatement at line 124 (pattern-matching, not policy
   enforcement; no tool-level ACL for agentic/MCP consumers; streaming crash
   isolation #10305). Patch-log-only disposition lets the shipped text
   mislead.
10. **Treat empty `cite-check-findings.json` (`[]`) on full-profile runs as
    suspicious**, not clean; fix `run spend` auto-credit (`agents_spawned: 0`
    after 55 spawns, `budget_usd: null` — assessment items 2/5).
11. **Do not adopt semantic caching for agentic traffic.** Report guardrails
    (threshold >=0.90, TTL <=60 min, single-shot only, shadow-mode first) are
    the minimum; FreshCache numbers (14.9% stale-error at 72% savings) argue
    for exact/prompt caching only in this ecosystem, where response cache is
    deliberately off for streaming.
12. Repo hygiene: `tests/test_mcp/test_update_note.py` fails at HEAD;
    `UV_FROZEN=1` vs `uv.lock` friction (assessment items 4/7).

## Live-config cross-check 2026-09-21 (same day)

Checked `~/.config/litellm/config.yaml` (28911 bytes) against the items above.
The gateway has moved past several report assumptions:

- **Superseded: item 1 (mimo prompt-cache passthrough).** No mimo/nemotron
  route exists in the live config (comment-only refs); production is
  Anthropic Max-OAuth based, and `enable_anthropic_prompt_caching: true`
  with `anthropic_prompt_caching_ttl: 1h` is already set, plus
  `prompt_caching` in `optional_pre_call_checks`. The 0%-hit finding was a
  property of the retired hyperresearch lane route, not the current gateway.
- **Done: item 2 (Phase 4 keys).** `phase4-keys.json` exists (daily +
  experiments keys issued). Remaining: verify per-key budget caps and add
  the spend dashboard; budget caps carry containment weight per tension 5.
- **Done: budget hardening.** `enforce_fallback_budget: true`,
  `fail_closed_budget_enforcement: true`, default team budget $50/30d,
  `proxy_budget_rescheduler_min_time: 300`, reset TZ US/Eastern.
- **Done with rationale: response-cache OFF.** `cache: false` + Redis txn
  buffer OFF both carry dated comments (streaming incompatibility,
  startup hard-fail coupling). Matches item 11's recommendation.
- **Done: reliability items.** `context_window_fallbacks`
  (pool_free -> anthropic-sonnet), `stream_timeout: 60`, `timeout: 600`,
  decoupled DB-dependency handling (`allow_requests_on_db_unavailable`),
  DB pool sizing, daily-only background probes (223 vs ~321k calls/day),
  `store_prompts_in_spend_logs: false`, 30d spend retention.
- **Residual gaps (propose, do not apply unilaterally):**
  `num_retries: 2` vs report's >= 3; no spend-anomaly alerting/webhook keys
  found in config — alerting coverage unverified.

## Key-budget audit 2026-09-21 (live, read-only via /key/list + /key/info)

- 7 keys total. `claude-all-max`: spend **$17,143 / $18,000 (95.2%)** with
  **no `budget_duration`** (lifetime cap, never resets), no TPM/RPM limits,
  no `max_parallel_requests`. At ~$579/day this exhausts in ~1.5 days and
  then hard-fails (fail-closed enforcement is on).
- `daily` + `experiments` (Phase 4 keys): **no `max_budget` at all** —
  Phase 4 containment incomplete. 3 further keys also uncapped (one carries
  tpm 1M / rpm 1000 only).
- Spend attribution gap: `spend_by_api_key` empty in
  `reports/spend_analysis.json`; `LATEST_SPEND_REPORT.md` has no per-key
  section. `analyze_spend.py` runs clean (report regenerated 2026-09-21;
  daily `litellm-spend-analysis.timer` active) but cannot attribute without
  key-tagged spend logs.
- Monitoring timers active (liveness, readiness, full, sync, verification,
  deployment, spend, credential, key-model health). No push alerting
  (webhook/Slack) anywhere — alerting is daily-report-only.
- Recommended: cap `daily`/`experiments` (e.g. $50/30d like the team
  default), set `budget_duration` on `claude-all-max` (or raise + window
  it), add `max_parallel_requests` per key (soft ceiling per tension 5),
  fix key attribution in spend logs, add threshold push alerting.

## num_retries conflict — RESOLVED: keep 2

User approved 2 -> 3, but the live config carries a deliberate 2026-09-20
decision the other way: `num_retries: 2` as a soft-fail net for a dead
combo pool, with `retry_policy` explicitly zeroing BadRequest/Auth/
ContentPolicy/RateLimit retries because all anthropic-* aliases share one
Max quota (a gateway 429 retry cannot succeed, only burns client wait).
The report's blanket >= 3 does not survive this local context. On
re-confirmation the user chose **(a) keep 2**. No gateway change made.

## Applied 2026-09-21 (user-approved, verified)

- **Budget caps**: `daily` + `experiments` capped $50/30d;
  `claude-all-max` windowed with `budget_duration: 30d` (cap stays $18k).
  Applied via direct token-table update (backup table
  `_backup_tokens_20260921`, 3 rows); verified live via `/key/info`
  past the 60s auth-cache TTL.
- **File threshold alerts**: `analyze_spend.py` now fetches per-key
  budgets from the token table (read-only psql, no secret needed) and
  writes `reports/SPEND_ALERTS.md` on every run (daily timer picks it up).
  Thresholds: key util WARN 80% / BREACH 95%; daily total vs 7d baseline
  WARN 1.5x / BREACH 2.0x; uncapped active keys WARN. First live run
  fires 1 BREACH (`claude-all-max` 95%) + 3 WARNs. Unit-checked with
  synthetic data (all severities + quiet cases pass). New code is
  `ruff format`-clean (one remaining format nit is pre-existing line 413).
- **Open, not approved**: capping `claude-code-openrouter` ($3.12 spend,
  uncapped) + 2 unnamed legacy keys; key attribution in spend logs
  (`spend_by_api_key` empty); vault hygiene (`test.txt`, junk filter);
  annotating the 4 skipped criticals in the litellm report text.

## Explicitly rejected transfers

- Exact response caching (breaks streaming; ecosystem already decided).
- Trusting gateway self-reported health; treating concurrency caps as hard
  boundaries; LiteLLM-native guardrails as policy enforcement.
