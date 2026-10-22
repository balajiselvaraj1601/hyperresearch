# Gate commands

The check is `phases/gate_check.py`. It uses the standard library and `uv run hyperresearch`. It does not import the hyperresearch package. It does not call `run step` or `run finish`.

From the workspace root:

```bash
TAG=<vault_tag> PHASE=B1 python3 apps/hyperresearch/queue/phases/gate_check.py
```

Optional:

```bash
REGISTRY_TIER=full TAG=<vault_tag> PHASE=B1 python3 apps/hyperresearch/queue/phases/gate_check.py
HPR_ROOT=/absolute/path/to/apps/hyperresearch TAG=<vault_tag> PHASE=B2 python3 apps/hyperresearch/queue/phases/gate_check.py
```

Exit codes:

| Exit | Decision | Worker may advance |
|---|---|---|
| 0 | Pass | yes |
| 2 | Conditional pass | yes, and the conditions stay in the JSON |
| 1 | Hold | no |
| 3 | Replan | no; B1 only, when `REGISTRY_TIER` disagrees with `pipeline_tier` |

Stdout is one JSON object. Append that object as one line of `dump/apps/hyperresearch/<slug>/output/runs/<vault_tag>/.work/gates.jsonl` only when you also add `ts` and you accept the decision. The worker does not accept its own artifacts. The watcher reads this file.

Full order: B1, B2, B3, B4, B5, B6, B7, B8, B9, B10, B11, B12, B13, B14, B14.5, B15, B16, then the watcher runs A4. Light order: B1, B2, B10, B15, B16, then A4. Calling a full-only phase on a light run returns Pass with `skipped: true`.

## Render check, every phase

From `apps/hyperresearch`:

```bash
uv run hyperresearch run contract "$TAG" "$STEP" | grep -E '<<|<vault_tag>' && echo HOLD || echo PASS
```

`$STEP` is `1`, `2`, `3`, `4`, `5`, `6`, `7`, `8`, `9`, `10`, `11`, `12`, `13`, `14`, `14.5`, `15`, or `16`.

## What each phase checks

| Phase | Mandatory evidence |
|---|---|
| B1 | Decomposition keys, no `Gap? = YES`, four shims, tier rationale |
| B2 | Note count versus 10/45/90, no uncovered row, coverage-gaps.md, at least one `claims-*.json`, redundancy audit on full |
| B3 | Both JSON arrays parse |
| B4 | Loci, dialectical or skip, numeric budgets, cap |
| B5 | Interim notes, each `note show` contains `## Committed position` |
| B6 | `comparisons.md` is more than a heading |
| B7 | Tension count in range, resolution and decision relevance |
| B8 | Gaps have ids, results file exists |
| B9 | Digest cites a source note. The count floor is advisory |
| B10 | Three drafts on full and the report was not written after them. The report on light |
| B11 | Pass-1 file, report, word count at or under the profile high, headings, no scaffold header |
| B12 | Four critic files. All four empty is a Hold |
| B13 | Post-critic fetch log |
| B14 | Named patch dispositions cover the critical count |
| B14.5 | Cite-check JSON, criticals disposed, manifest step `14.5` is `done` |
| B15 | Polish log is not the empty stub. Four lint rules exit 0 |
| B16 | Recommendations and decisions |
| A4 | Manifest `status` is `done` and `verify.passed` is true. Read only |

## Ship command, watcher only

```bash
cd apps/hyperresearch
uv run hyperresearch run finish "$TAG" -j
```

Then:

```bash
TAG="$TAG" PHASE=A4 python3 apps/hyperresearch/queue/phases/gate_check.py
```

## Resume does not list 14.5

```bash
cd apps/hyperresearch
uv run hyperresearch run resume litellm-cost-perf-ops-506ad8 --json
```

`done_steps` on that finished run is `"1"` through `"16"` and omits `"14.5"`. The manifest still has `steps["14.5"].status` = `done`. Full runs insert B14.5 by this table, not by `next_step`.

## Bookkeeping after exit 0 or 2

```bash
cd apps/hyperresearch
uv run hyperresearch run step "$TAG" "$STEP" --status done -j
printf '%s\n' "$(date -u +%FT%TZ) $STEP done" >> "dump/apps/hyperresearch/<slug>/output/runs/<vault_tag>/.work/status.log"
```

Mark the step `running` when the phase starts. A crash leaves `running`, which resume treats as not done.
