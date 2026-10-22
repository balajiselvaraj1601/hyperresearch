# Phase map: every hyperresearch topic, end to end

Template: `PHASE-TEMPLATE.md` in this folder. Every phase below is an
instance of that template. Only phase specific fields are shown here: the
universal loop, invariants, gate outcomes, gate line shape, and handoff
rules from the template apply to every row without exception.

Naming and connection keys, identical in every system:
`slug` (registry) -> `vault_tag` `<slug>-<6hex>` (vault) ->
tmux session `orch-hyperresearch-<slug>` -> published report
`knowledge/hyperresearch/<slug>.md`.

## Level A: topic lifecycle (one pass per registry row)

### A0 Intake

- Purpose: is this topic stated well enough to research unattended?
- Owner: operator writes the row, watcher validates.
- Entry: registry file exists and parses. Check: `registry_watcher.py --validate`.
- Work: add one row (slug, title, exactly one of prompt or prompt_file,
  tier light or full or blank for light, priority). Status pending.
- Exit: validator passes. Duplicate slug, bad tier, or missing prompt is Hold.
- Verify: test, validator exit code. Acceptor: watcher.
- Evidence: the registry row itself.
- Handoff: row visible as pending to the next watcher tick.

### A1 Claim and scaffold

- Purpose: is capacity free and the run scaffolded under a unique tag?
- Owner: watcher, in one timer tick.
- Entry: no row in claimed, running, or verifying (concurrency 1). Check:
  watcher claim rule under file lock.
- Work: claim highest priority then oldest pending row. Mint `vault_tag`
  with `uv run hyperresearch vault-tag <slug> -j`. Write the verbatim prompt
  to a query file. Scaffold with
  `run init <vault_tag> --profile <tier> --query-file <file>`.
- Exit: `dump/apps/hyperresearch/<slug>/output/runs/<vault_tag>/run.json` exists, `query.md` matches the
  commissioned prompt byte for byte, registry row carries `vault_tag`.
- Verify: test plus inspection of `query.md`. Acceptor: watcher.
- Abort: claim older than 15 minutes with no session returns to pending.
- Handoff: brief rendered into `dump/apps/hyperresearch/<slug>/output/runs/<vault_tag>/.work/brief.txt` for A2.

### A2 Worker launch (tmux)

- Purpose: is exactly one phase driver live on this topic, in its own lane?
- Owner: watcher launches. The tmux session runs `registry_watcher.py
  --drive` for this slug. Inside that process, each phase is one Muse exec
  or one OpenCode run (`runner` on the row; blank means muse).
- Entry: A1 gate Pass. `tmux has-session -t orch-hyperresearch-<slug>` is
  false. `command -v tmux` succeeds, and so does `muse` or `opencode` for
  the selected runner.
- Work: create the tmux session. The session command is this watcher with
  `--drive --registry <path> --slug <slug>`. For each phase still open in
  `gates.jsonl`, the driver writes one phase brief, then runs either
  `muse exec --prompt-file brief.txt` with `--workspace apps/hyperresearch
  --trust-workspace --disable-approval --disable-sandbox --sandbox-network
  enabled`, or `opencode run --standalone --auto --format json --file
  brief.txt` in that same workspace (tmux working directory; no model flag).
  It waits for that process, then runs `phases/gate_check.py` with `TAG`,
  `PHASE`, `REGISTRY_TIER`, and `HPR_ROOT` set to the dump topic root.
  `UV_CACHE_DIR` is under `/tmp` (Phase 0 spike proved the sandboxed default
  cannot write the uv cache and an untrusted workspace disables delegation).
  Tee the log to `<slug>/.work/worker.log`. Set row running.
- Exit: session listed by `tmux ls`, log file growing, `session_name`
  recorded. One topic per session, never multiplexed.
- Verify: demonstration, `tmux ls` plus first log lines. Acceptor: watcher.
- Abort: session dies while the row is still `running` and the manifest is
  not done. Reconcile counts an attempt: back to pending for resume below 2
  attempts, failed at 2. A gate Hold or Replan sets the row `blocked` before
  the driver exits, so that exit is not counted as a crash.
- Handoff: the driver owns the phase loop. The 5-minute tick does not walk
  phases.

### A3 Research execution (contains all Level B phases)

- Purpose: did every tier phase pass its own gate?
- Owner: the phase driver. Each Muse or OpenCode process does one phase and
  does not call `run finish`. The driver is the only caller of the phase gate.
- Entry: A2 gate Pass. The first phase whose last `gates.jsonl` line is not
  Pass or Conditional pass. Inside that phase, `run resume` is the step
  entry when the step is unfinished, never a restart at step 1.
- Work: light runs B1, B2, B10, B15, B16. Full runs B1 through B16, with
  B14.5 between B14 and B15 even when `run resume` reports step 15.
- Exit: every tier phase has a Pass or Conditional pass line in
  `gates.jsonl`. The driver then runs `run verify` and `run finish`.
- Verify: `gate_check.py` exit codes against the dump topic directory. Exit
  0 or 2 advances and the driver appends the gate line. Exit 1 is Hold and
  exit 3 is Replan: the row becomes `blocked` and the next phase is not
  started. A live session with a stale heartbeat is a stall: capture the
  pane, report, never kill silently.
- Handoff: manifest status `done` moves the row to verifying on the next
  tick. Publish stays A5.

### A4 Ship gate

- Purpose: does the vault itself accept this report?
- Owner: watcher runs the gate. The worker may have run it already; the
  watcher trusts only the manifest.
- Entry: session ended or `DONE` seen, manifest present.
- Work: if manifest status is not done, run `uv run hyperresearch run
  finish <vault_tag> -j`. Fail means blocked, exit 1, by vault design.
- Exit: manifest status done (finish passed true). This is the only path to
  done. Hand reinterpreting checks is forbidden by the vault contract.
- Verify: test, finish exit code plus manifest status. Acceptor: vault gate.
- Abort: failed gate sets row blocked with the failing check in `error`.
  Re-entry is a resumed worker fixing the report, then A4 again.
- Handoff: exactly one `final_report_<vault_tag>.md` under
  `dump/apps/hyperresearch/<slug>/output/reports/<vault_tag>/` is the publish source.

### A5 Publish and close

- Purpose: is the accepted report filed where the operator reads it?
- Owner: watcher.
- Entry: A4 gate Pass.
- Work: copy the vault report to `knowledge/hyperresearch/<slug>.md`.
  That directory holds only those task-named reports. Notes, the run
  manifest, and worker scratch stay in the vault.
- Exit: sha256 of the copy equals sha256 of the vault report. Only then set
  row done with `finished_at` and `final_report`.
- Verify: test, checksum. Acceptor: watcher. Publishing a done row again is
  a no op.
- Closure disposition: tmux session for this topic is gone or killed by
  scoped cleanup (only `orch-hyperresearch-` sessions this system created).
  Open conditions from any Conditional pass stay in `gates.jsonl`,
  never dropped.

## Level B: research phases inside A3 (owner: muse or opencode worker)

Procedure source for every row: `hyperresearch run contract <vault_tag> <N>`,
rendered fresh at the moment the phase runs. Raw files under
`src/hyperresearch/skills/` are templates with unresolved placeholders and
are never executed directly. Tier key: L = light runs it, F = full runs it.

| Phase | Step | Question it answers | Entry (key inputs) | Exit evidence (mandatory) | Tier |
|---|---|---|---|---|---|
| B1 | 1 Decompose | What exactly was asked, item by item? | `query.md`, `scaffold.md` | `prompt-decomposition.json` valid, tier and headings set, coverage matrix with zero Gap rows, shims rendered | L F |
| B2 | 2 Width sweep | Is every atomic item covered by sources? | decomposition, coverage matrix | per tier source minimum met, no uncovered items, `coverage-gaps.md` written | L F |
| B3 | 3 Contradiction graph | Where does the evidence actually fork? | corpus notes from B2 | ranked fight clusters artifact per contract | F |
| B4 | 4 Loci analysis | Which few questions deserve depth? | contradiction graph, decomposition | `loci.json` scored, within budget, at least one dialectical locus per contract | F |
| B5 | 5 Depth investigation | What position survives per locus? | `loci.json` | one interim note per locus, each ending in a committed position | F |
| B6 | 6 Cross locus reconcile | Where do the positions conflict? | interim notes | `comparisons.md` naming the tensions | F |
| B7 | 7 Source tensions | Which experts disagree, on record? | corpus, `comparisons.md` | `source-tensions.json` per contract | F |
| B8 | 8 Corpus critic | What would overturn this direction? | corpus, positions | `corpus-critic-gaps.json`, gap fetch done or gaps named | F |
| B9 | 9 Evidence digest | Which claims and quotes carry the draft? | filtered corpus | `evidence-digest.md`, quotes verbatim from vault notes | F |
| B10 | 10 Triple draft | What do independent angles conclude? | decomposition, digest (F) or corpus (L) | F: three drafts in `temp/draft-{a,b,c}.md`. L: single draft straight to final report path | L F |
| B11 | 11 Synthesize | What is the one integrated report? | three drafts | `final_report_<vault_tag>.md` written once, length counted mechanically | F |
| B12 | 12 Critics x4 | What is wrong with it, from four angles? | synthesized report | four `critic-findings-*.json` files, separate role spawns | F |
| B13 | 13 Gap fetch | Can critic gaps be evidenced from the vault? | critic findings | new notes fetched for fillable gaps, rest named unfillable | F |
| B14 | 14 Patch | Are findings applied without regeneration? | findings, report | `patch-log.json`: every critical finding applied or skipped by name, surgical hunks only | F |
| B14.5 | 14.5 Cite check | Does every citation support its sentence? | patched report | `cite-check-findings.json`, dangling citations fixed or sentence deleted | F |
| B15 | 15 Polish | Is it clean, with integrity intact? | report, patch log | `polish-log.json` populated, integrity and lint gates pass | L F |
| B16 | 16 Readability | Is it scannable without content change? | polished report | `readability-decisions.json` records each suggestion applied or rejected | L F |

Per phase Level B gate line (worker appends before advancing):
decision, criterion results with artifact paths, verifier. Stepping the
manifest (`run step`) without a matching gate line, or a gate line whose
evidence path is missing or placeholder, is a Hold at A3 verification.

Light tier sequence: A3 runs B1, B2, B10, B15, B16.
Full tier sequence: A3 runs B1 to B16 including B14.5.
Tier is classified again inside B1 by the vault. If B1 tier and registry
tier disagree, that is Replan at the B1 gate, never a silent upgrade. The
worker records it and continues only under the registry tier unless the
operator changes the row.

## Connection checklist (verified at A5)

- Registry row, `run.json`, and `gates.jsonl` agree on `vault_tag` and tier.
- Every Level B phase in the tier has exactly one final gate line with
  decision Pass or Conditional pass, plus any earlier Hold lines preserved.
- Every exit evidence path in the table above exists for phases that ran.
- `knowledge/hyperresearch/<slug>.md` matches the vault report byte for byte.
- No `orch-hyperresearch-<slug>` session remains after close.
