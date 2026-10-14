# Hyperresearch — Mimo-worker variant

One prompt in, adversarially-audited report out: a 16-step research pipeline where an orchestrator sequences the work and small models do the unit tasks (every worker runs on Xiaomi Mimo through LiteLLM, `pool_mimo`). Forked from [jordan-gibbs/hyperresearch](https://github.com/jordan-gibbs/hyperresearch) (v0.10.0); full CLI and vault reference: the [upstream README](https://github.com/jordan-gibbs/hyperresearch#readme).

## Pipeline map

`1 Decompose → 2 Width sweep → 3 Contradiction graph → 4 Loci → 5 Depth investigation → 6 Reconcile → 7 Source tensions → 8 Corpus critic → 9 Evidence digest → 10 Triple draft → 11 Synthesize → 12 Critics ×4 → 13 Gap fetch → 14 Patch → 14.5 Cite-check → 15 Polish → 16 Readability → ship gate` (`run finish`).

Light tier: 1 → 2 → 10 → 15 → 16 (~30–40 min). Full tier: all 16 (~1.5–2.5 h). Dissertation (opt-in) loops steps 2–10 per chapter.

## The steps, in brief

- **0 Mimo preflight** — probes the `pool_mimo` pool before any spend; on failure the run blocks, never silently substitutes a model.
- **1 Decompose** — atomic items + `required_section_headings`, tier/format/citation, coverage self-audit.
- **2 Width sweep** — 40–100 scored searches in batches of 8–12, fetched in waves of 2; citation-chain chasing; period-pinned filings for their exact period.
- **3 Contradiction graph → 4 Loci** — ranked fight clusters; ≤6 scored depth loci with a 40-source budget (≥1 dialectical).
- **5 Depth → 6 Reconcile → 7 Source tensions → 8 Corpus critic** — one interim note per locus ending in `## Committed position`; 3–5 named tensions; gap fetch for what would overturn the direction.
- **9 Evidence digest → 10 Triple draft** — scripted evidence filter; 3 drafts (strongest-thesis, steelman-contrarian, synthesis), each a ≤50-line digest; light tier writes one draft straight to the report path.
- **11 Synthesize** — write-once from here: per-section writers, mechanical length count, one compression pass.
- **12 Critics ×4 → 13 Gap fetch → 14 Patch → 14.5 Cite-check** — findings applied as grep-verified surgical hunks only; dangling citations fixed or the sentence deleted.
- **15 Polish → 16 Readability** — net-negative, checksum-verified cleanup + lint battery; ≤50 impact-ranked suggestions applied in fixed order.

## Worker model: Mimo via LiteLLM

Profile lives in `.hyperresearch/config.toml` (`[profile.mimo]`, `pool_mimo` model aliases, wave widths and caps). Enable per vault with `hyperresearch profile use mimo --json` (revert: `hyperresearch profile use full`). Since v8 no agent files are installed: workers are generic `agent_medium` spawns and what makes one a fetcher or critic is its **role brief**, rendered per run —

```bash
hyperresearch run contract <vault_tag> <N>              # the step's procedure
hyperresearch run contract <vault_tag> --role fetcher   # a worker's role brief
hyperresearch run contract <vault_tag> --list-roles
```

Briefs live in `src/hyperresearch/skills/roles/`; raw `src/hyperresearch/skills/*.md` are templates (unresolved placeholders until rendered).

## Enforced

Verbatim prompt as gospel; locus coverage; patch-only modification after synthesis (`run verify` fails unless every critical critic finding is applied or skipped by name in `patch-log.json`); quoted text must exist verbatim in a vault note; fetched web text is fenced as data, never instructions; `run finish` must report `"passed": true`.

## Output layout

Each run keeps `output/reports/<vault_tag>/final_report_*.md`, `output/notes/<vault_tag>/<note-id>.md`, and `output/runs/<vault_tag>/` (scaffold, critics, patch logs). `hyperresearch fetch --tag <vault_tag>` writes notes into that run's notes dir; sync skips `output/reports/`.

## Install

`pip install hyperresearch && hyperresearch install`, then `/hyperresearch <anything>` in Claude Code. Python 3.11–3.13, [Claude Code](https://claude.com/claude-code), and a LiteLLM proxy serving the `mimo` / `pool_mimo` aliases. License: [MIT](LICENSE).
