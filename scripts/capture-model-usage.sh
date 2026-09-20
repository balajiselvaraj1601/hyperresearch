#!/usr/bin/env bash
# capture-model-usage.sh — per-step model-usage snapshot for hyperresearch runs.
#
# Queries LiteLLM's spend logs (postgres in the litellm-db container) for request
# counts + tokens grouped by model_group/model since a given ISO timestamp, and
# appends one JSONL record to the run's model-usage log. This is how a run proves
# WHICH models actually served traffic (orchestrator Sonnet vs gemma_bulk workers
# vs silent flash_lite/Claude fallbacks) — the served model, not the spawn request.
#
# Usage:
#   capture-model-usage.sh <vault_tag> <step_label> [since_iso] [research_dir] [session_id]
# Example:
#   capture-model-usage.sh continuity-abc123 step-02
#
# since_iso defaults to the run's anchor file
# (<research_dir>/runs/<vault_tag>/temp/model-usage-anchor.txt; seeded with
# UTC now if missing). After a successful capture the anchor is advanced to
# the current time, so consecutive two-arg calls form contiguous windows —
# no command substitution needed in the caller (keeps the invocation a
# statically-analyzable prefix for permission allow rules).
#
# session_id defaults to $CLAUDE_CODE_SESSION_ID (set by Claude Code in the
# orchestrator's shell) and scopes the spend-log query to THIS run's session,
# so concurrent sessions on the proxy no longer pollute the counts. Empty
# session_id falls back to the old proxy-wide window (ratios only).
#
# Output: appends {"step": ..., "since": ..., "session_id": ..., "captured_at": ...,
# "models": [...]} to <research_dir>/runs/<vault_tag>/temp/model-usage.jsonl
# and echoes the record.
set -euo pipefail

VAULT_TAG="${1:?vault_tag required}"
STEP="${2:?step label required (e.g. step-02)}"
SINCE="${3:-}"
RESEARCH_DIR="${4:-research}"
SESSION_ID="${5:-${CLAUDE_CODE_SESSION_ID:-}}"

OUT_DIR="${RESEARCH_DIR}/runs/${VAULT_TAG}/temp"
mkdir -p "$OUT_DIR"
OUT="${OUT_DIR}/model-usage.jsonl"
ANCHOR_FILE="${OUT_DIR}/model-usage-anchor.txt"

if [ -z "$SINCE" ]; then
	[ -f "$ANCHOR_FILE" ] || date -u +"%Y-%m-%d %H:%M:%S" >"$ANCHOR_FILE"
	SINCE="$(cat "$ANCHOR_FILE")"
fi

SESSION_FILTER=""
if [ -n "$SESSION_ID" ]; then
	case "$SESSION_ID" in
	*[!a-zA-Z0-9-]*)
		echo "capture-model-usage: invalid session_id '$SESSION_ID'" >&2
		exit 1
		;;
	esac
	SESSION_FILTER=" AND session_id = '${SESSION_ID}'"
fi
SQL="SELECT COALESCE(model_group, model) AS mg, model, COALESCE(status,'') AS status, COUNT(*) AS requests, COALESCE(SUM(total_tokens),0) AS tokens FROM \"LiteLLM_SpendLogs\" WHERE \"startTime\" >= '${SINCE}'${SESSION_FILTER} GROUP BY 1, 2, 3 ORDER BY requests DESC;"

ROWS=$(docker exec litellm-db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAF'|' -c \"${SQL//\"/\\\"}\"")

export ROWS STEP SINCE OUT SESSION_ID
python3 - <<'PYEOF'
import os, json, datetime
models = []
for line in os.environ["ROWS"].splitlines():
    line = line.strip()
    if not line:
        continue
    mg, model, status, req, tok = line.split("|")
    models.append({"model_group": mg, "model": model, "status": status,
                   "requests": int(req), "tokens": int(tok)})
rec = {
    "step": os.environ["STEP"],
    "since": os.environ["SINCE"],
    "session_id": os.environ.get("SESSION_ID") or None,
    "captured_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "models": models,
}
with open(os.environ["OUT"], "a") as f:
    f.write(json.dumps(rec) + "\n")
print(json.dumps(rec, indent=1))
PYEOF

date -u +"%Y-%m-%d %H:%M:%S" >"$ANCHOR_FILE"
