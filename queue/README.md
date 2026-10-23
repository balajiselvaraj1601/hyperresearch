# Hyperresearch topic queue

One row is one topic. The watcher claims at most one unfinished topic at a
time, launches one Muse or OpenCode session, and publishes the accepted
report as `knowledge/hyperresearch/<slug>.md`.
Research notes, the working report, and the topic database stay under
`dump/apps/hyperresearch/<slug>/`.
This folder holds the operator kit. The queue file is
`warehouse/registry/hyperresearch_registry.csv`.

Canonical command, from `apps/hyperresearch`:

```bash
uv run hyperresearch
```

The system `hyperresearch` shim is broken on this host. Do not add a
`[profile.mimo]` section. The worker is Muse or OpenCode. Blank `runner`
means Muse.

## Who writes which columns

Input columns, written by the operator on `pending` rows only:

`topic_id`, `slug`, `title`, `prompt`, `prompt_file`, `tier`, `priority`, `notes`, `runner`.

State columns, written only by `apps/hyperresearch/scripts/registry_watcher.py`:

`status`, `vault_tag`, `output_dir`, `session_name`, `attempts`, `created_at`,
`claimed_at`, `started_at`, `finished_at`, `final_report`, `error`.

`status` is one of `pending`, `claimed`, `running`, `verifying`, `done`,
`failed`, `blocked`, `skipped`.

`tier` is `light` or `full`. Blank means `light`. `runner` is `muse` or
`opencode`. Blank means `muse`. Set exactly one of `prompt` or `prompt_file`.
`slug` is lowercase, starts with a letter or digit, and may contain dashes.

The watcher locks the file and replaces it with an atomic rename. Edit a
`pending` row only while the watcher is paused.

## Queue a topic

Add one `pending` row. Leave the state columns empty. `priority` is an
integer; higher runs first, then the oldest `created_at`. The queue file is
`warehouse/registry/hyperresearch_registry.csv`. A header-only file is a
valid empty queue. The published report is
`knowledge/hyperresearch/<slug>.md`. A relative `prompt_file` is resolved
next to the registry file.

Check the row:

```bash
python3 apps/hyperresearch/scripts/registry_watcher.py --validate
```

See the one row the next tick would claim. This does not write the file:

```bash
python3 apps/hyperresearch/scripts/registry_watcher.py --dry-run
```

## Runners

The tmux session runs the phase driver. Each phase is one fresh Muse exec
or one OpenCode run of that phase's brief. The driver runs the phase gate
before the next phase. After the last phase passes, the driver runs `run
verify` and `run finish`. The phase session does not. The watcher claims,
launches, reconciles, and publishes. The worker does not edit the registry.

| `runner` | Launch |
|---|---|
| blank or `muse` | `muse exec --prompt-file` with the phase-map workspace flags |
| `opencode` | `opencode run --standalone --auto --format json --file` the same brief. Workspace is the tmux working directory. No model flag; OpenCode uses its own config. |

No other coding CLI is launched. Session name stays `orch-hyperresearch-<slug>`
for both.

## What a tick does

One pass, then exit. It does not wait for research to finish.

1. Reconcile. A `running` row whose tmux session is gone and whose run is
   unfinished goes back to `pending` below 2 attempts and to `failed` at 2.
   A `running` row whose manifest status is `done` moves to `verifying`.
   A `claimed` row older than 15 minutes with no session returns to `pending`.
2. Publish a `verifying` row only when `uv run hyperresearch run verify` and
   `run finish` both pass and the sha256 of
   `knowledge/hyperresearch/<slug>.md` matches the vault report.
   A failed check or a checksum mismatch sets `blocked` and names the check
   in `error`. Publishing a `done` row again does nothing.
3. If nothing is `claimed`, `running`, or `verifying`, claim the next
   `pending` row and start `orch-hyperresearch-<slug>`.

The worker brief is `dump/apps/hyperresearch/<slug>/output/runs/<vault_tag>/.work/brief.txt`.
The session log is beside that brief. A done topic is one file,
`knowledge/hyperresearch/<slug>.md`. Vault notes stay in the dump topic directory.

## Watch logs

```bash
journalctl --user -u hyperresearch-watcher -n 80 --no-pager
```

Per topic:

```bash
tail -f dump/apps/hyperresearch/<slug>/output/runs/<vault_tag>/.work/worker.log
```

`tmux ls` shows `orch-hyperresearch-<slug>` while that topic is running.

Phase gates are in `.work/gates.jsonl` beside the log, one line per phase.
The driver streams each worker's output into `worker.log`, records a
`heartbeat` event every 10 minutes while a phase runs, and kills a phase
after 4 hours (the row is blocked with `worker exited 124`).

## OpenCode lane

- Do not run a non-standalone `opencode` command (`opencode session list`,
  `export`, `service`) while a topic runs. It starts the background service,
  and the running worker receives "The server restarted" and loses its
  in-flight subagents. Watch the files above instead.
- An opencode drive holds `$XDG_RUNTIME_DIR/opencode-account-switch.lock`
  shared. The 5-hourly account switch then skips that cycle instead of
  restarting the service mid-run.
- Workers get the driver's interpreter directory first on `PATH`. The uv-tool
  `hyperresearch` and `hpr` in `~/.local/bin` are a stale snapshot of this repo.
- The model is OpenCode's configured default. No model flag is passed.

## Pause, resume, disable

The timer unit is a recorded copy under
`governance_management/utils/heartbeat/hyperresearch/`. Installing it is a
separate operator step. This tree does not install or enable it.

Pause launches (the current tmux session keeps running):

```bash
systemctl --user stop hyperresearch-watcher.timer
```

Resume:

```bash
systemctl --user start hyperresearch-watcher.timer
```

Disable future ticks:

```bash
systemctl --user disable --now hyperresearch-watcher.timer
```

Confirm it is not enabled:

```bash
systemctl --user is-enabled hyperresearch-watcher.timer
```

## Rollback

Stop future launches with `disable --now`, as above. Kill only sessions
this queue created:

```bash
tmux list-sessions -F '#{session_name}' | grep '^orch-hyperresearch-' | xargs -r -n1 tmux kill-session -t
```

Reset a non-terminal row by hand after the timer is stopped: set `status`
back to `pending` and clear `session_name` if you want the next tick to
claim it again. A `blocked` row needs the failing check fixed in the vault,
then `status` set to `verifying` so the next tick reruns the ship gate.
Do not delete `knowledge/hyperresearch/<slug>.md` or the dump topic directory.

## Install the recorded units

Copy, do not author a second pair:

```bash
install -m 0644 governance_management/utils/heartbeat/hyperresearch/hyperresearch-watcher.service ~/.config/systemd/user/
install -m 0644 governance_management/utils/heartbeat/hyperresearch/hyperresearch-watcher.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hyperresearch-watcher.timer
```

The timer fires every 5 minutes with `Persistent=true`. The service is a
oneshot tick.
