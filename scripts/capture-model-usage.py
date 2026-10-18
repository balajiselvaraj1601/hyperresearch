#!/usr/bin/env python3
"""Append one LiteLLM spend-log snapshot for a hyperresearch step.

Usage: capture-model-usage.py <vault_tag> <step_label> [since_iso] [research_dir] [session_id]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _parse_capture_args(argv: list) -> tuple:
    if not argv or argv[0] == "":
        print("capture-model-usage.sh: 1: vault_tag required", file=sys.stderr)
        raise SystemExit(1)
    if len(argv) < 2 or argv[1] == "":
        print(
            "capture-model-usage.sh: 2: step label required (e.g. step-02)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return (
        argv[0],
        argv[1],
        argv[2] if len(argv) > 2 else "",
        argv[3] if len(argv) > 3 else "research",
        argv[4] if len(argv) > 4 else os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
    )


def _resolve_since(out_dir: Path, anchor: Path, since: str) -> str:
    if since:
        return since
    if not anchor.is_file():
        anchor.write_text(
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S") + "\n",
            encoding="utf-8",
        )
    return anchor.read_text(encoding="utf-8").strip()


def _session_filter(session_id: str) -> str:
    if not session_id:
        return ""
    if re.search(r"[^a-zA-Z0-9-]", session_id):
        print(f"capture-model-usage: invalid session_id '{session_id}'", file=sys.stderr)
        raise SystemExit(1)
    return f" AND session_id = '{session_id}'"


def _query_spend_logs(since: str, session_filter: str) -> tuple:
    """Run the spend-log query. Returns (returncode, stdout)."""
    sql = (
        "SELECT COALESCE(model_group, model) AS mg, model, COALESCE(status,'') AS status, "
        "COUNT(*) AS requests, COALESCE(SUM(total_tokens),0) AS tokens "
        'FROM "LiteLLM_SpendLogs" WHERE "startTime" >= '
        f"'{since}'{session_filter} GROUP BY 1, 2, 3 ORDER BY requests DESC;"
    )
    quoted = sql.replace('"', '\\"')
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "litellm-db",
            "sh",
            "-c",
            f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAF\'|\' -c "{quoted}"',
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or proc.stdout or "")
        return proc.returncode or 1, ""
    return 0, proc.stdout or ""


def _parse_model_lines(text: str) -> list:
    models = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        group, model, status, requests, tokens = line.split("|")
        models.append(
            {
                "model_group": group,
                "model": model,
                "status": status,
                "requests": int(requests),
                "tokens": int(tokens),
            }
        )
    return models


def _write_usage_record(
    out: Path, anchor: Path, step: str, since: str, session_id: str, models: list
) -> None:
    record = {
        "step": step,
        "since": since,
        "session_id": session_id or None,
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "models": models,
    }
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    print(json.dumps(record, indent=1))
    anchor.write_text(
        datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S") + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    vault, step, since, research, session_id = _parse_capture_args(argv)

    out_dir = Path(research) / "runs" / vault / "temp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "model-usage.jsonl"
    anchor = out_dir / "model-usage-anchor.txt"
    since = _resolve_since(out_dir, anchor, since)
    session_filter = _session_filter(session_id)

    code, text = _query_spend_logs(since, session_filter)
    if code:
        return code
    _write_usage_record(out, anchor, step, since, session_id, _parse_model_lines(text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
