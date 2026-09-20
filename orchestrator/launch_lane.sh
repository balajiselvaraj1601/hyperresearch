#!/usr/bin/env bash
# launch_lane.sh <vault_tag> <session_name>
#
# Start one detached tmux session running `cca --model mimo
# --dangerously-skip-permissions` and hand it a prompt to drive the named
# hyperresearch run to completion via the local hyperresearch-pipeline skill.
#
# The session IS the orchestrator (top-level model = mimo), not a subagent
# spawn — this avoids the 8k-output-token Task-tool cap that produced
# schema-shaped placeholder content on the earlier subagent-based attempt.
set -euo pipefail

VAULT_TAG=${1:?usage: launch_lane.sh <vault_tag> <session_name>}
SESSION=${2:?usage: launch_lane.sh <vault_tag> <session_name>}

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

if tmux has-session -t "$SESSION" 2>/dev/null; then
	echo "launch_lane: session $SESSION already exists — attach: tmux attach -t $SESSION" >&2
	exit 0
fi

mkdir -p orchestrator/logs
LOG_FILE="orchestrator/logs/${SESSION}.log"
STATUS_FILE="orchestrator/logs/${SESSION}.status"
: >"$LOG_FILE"

tmux new-session -d -s "$SESSION" -n pipeline -c "$REPO_ROOT" \
	"exec cca --model mimo --dangerously-skip-permissions"
tmux pipe-pane -t "$SESSION:pipeline" -o "cat >> $(printf '%q' "$REPO_ROOT/$LOG_FILE")"

# --dangerously-skip-permissions shows a one-time interactive confirmation
# dialog ("Bypass Permissions mode" warning) with "No, exit" as the default
# highlighted option. Accept it explicitly: Down to select "Yes, I accept",
# then Enter.
ACCEPTED=0
for _ in $(seq 1 30); do
	dead=$(tmux list-panes -t "$SESSION:pipeline" -F '#{pane_dead}' 2>/dev/null || echo 1)
	[ "$dead" = "1" ] && break
	if tmux capture-pane -pt "$SESSION:pipeline" 2>/dev/null | grep -q 'Bypass Permissions mode'; then
		tmux send-keys -t "$SESSION:pipeline" Down
		tmux send-keys -t "$SESSION:pipeline" Enter
		ACCEPTED=1
		break
	fi
	sleep 1
done

READY=0
for _ in $(seq 1 90); do
	dead=$(tmux list-panes -t "$SESSION:pipeline" -F '#{pane_dead}' 2>/dev/null || echo 1)
	if [ "$dead" = "1" ]; then
		echo "launch_lane: pane died before becoming ready — check $LOG_FILE" >&2
		exit 1
	fi
	if tmux capture-pane -pt "$SESSION:pipeline" 2>/dev/null | grep -q 'Claude Code v'; then
		READY=1
		break
	fi
	sleep 1
done
[ "$ACCEPTED" -eq 1 ] || echo "launch_lane: warning — bypass-permissions dialog not seen, may not have needed accepting" >&2

if [ "$READY" -ne 1 ]; then
	tmux kill-session -t "$SESSION" 2>/dev/null || true
	echo "launch_lane: session did not become ready within 90s — log: $LOG_FILE" >&2
	exit 1
fi

PROMPT="Use the hyperresearch-pipeline skill. Vault tag: ${VAULT_TAG}. Working directory: ${REPO_ROOT}. Run \`hyperresearch run status ${VAULT_TAG} -j\` to find next_step, then drive the pipeline to completion one step at a time using the matching hyperresearch-N-* skill for each step. Each step's procedure comes from \`hyperresearch run contract ${VAULT_TAG} <N>\` (rendered; never read the raw src/hyperresearch/skills/*.md), and every subagent spawn ends with its role brief from \`hyperresearch run contract ${VAULT_TAG} --role <role>\` pasted verbatim, with absolute paths only. Verify each step's manifest transition AND output artifact content before advancing — a done status alone is not proof; read the artifact and reject placeholder/null content (null position fields, unfilled [bracket] template text, thin orphan-scan-only results), re-running the step if you find it. On database-locked errors, sleep and retry at most twice; never kill or delete the database, WAL, or lock files. When all steps are done, run \`hyperresearch run verify ${VAULT_TAG}\` then \`hyperresearch run finish ${VAULT_TAG}\`. After every step transition, append one line to ${STATUS_FILE} recording the step number and status."

tmux send-keys -t "$SESSION:pipeline" -l "$PROMPT"
tmux send-keys -t "$SESSION:pipeline" Enter

echo "launch_lane: $SESSION started for $VAULT_TAG — log: $LOG_FILE, status: $STATUS_FILE"
