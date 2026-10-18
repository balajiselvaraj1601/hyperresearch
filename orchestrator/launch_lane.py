#!/usr/bin/env python3
"""launch_lane.py <vault_tag> <session_name>

Start one detached tmux session running cca and hand it the pipeline prompt.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

USAGE = "usage: launch_lane.sh <vault_tag> <session_name>"


def _need(index: int) -> int:
    print(f"{Path(sys.argv[0]).name}: {index}: {USAGE}", file=sys.stderr)
    return 1


def _pane_dead(session: str) -> str:
    proc = subprocess.run(
        ["tmux", "list-panes", "-t", f"{session}:pipeline", "-F", "#{pane_dead}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return "1"
    return (proc.stdout or "1").strip() or "1"


def _pane_text(session: str) -> str:
    proc = subprocess.run(
        ["tmux", "capture-pane", "-pt", f"{session}:pipeline"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


def _parse_lane_args(argv: list[str]) -> tuple:
    if not argv or argv[0] == "":
        raise SystemExit(_need(1))
    if len(argv) < 2 or argv[1] == "":
        raise SystemExit(_need(2))
    return argv[0], argv[1]


def _session_exists(session: str) -> bool:
    has = subprocess.run(
        ["tmux", "has-session", "-t", session],
        check=False,
        stderr=subprocess.DEVNULL,
    )
    return has.returncode == 0


def _run_or_code(args: list, **kwargs) -> int:
    proc = subprocess.run(args, check=False, **kwargs)
    if proc.returncode:
        return proc.returncode
    return 0


def _wait_for_accept(session: str) -> bool:
    for _ in range(30):
        if _pane_dead(session) == "1":
            return False
        if "Bypass Permissions mode" in _pane_text(session):
            subprocess.run(["tmux", "send-keys", "-t", f"{session}:pipeline", "Down"], check=False)
            subprocess.run(["tmux", "send-keys", "-t", f"{session}:pipeline", "Enter"], check=False)
            return True
        time.sleep(1)
    return False


def _wait_for_ready(session: str, log_file: Path):
    """Wait for the ready marker. Returns True (ready), False (died), None (timeout)."""
    for _ in range(90):
        if _pane_dead(session) == "1":
            print(
                f"launch_lane: pane died before becoming ready — check {log_file}",
                file=sys.stderr,
            )
            return False
        if "Claude Code v" in _pane_text(session):
            return True
        time.sleep(1)
    return None


def _abort_not_ready(session: str, log_file: Path) -> int:
    subprocess.run(["tmux", "kill-session", "-t", session], check=False, stderr=subprocess.DEVNULL)
    print(
        f"launch_lane: session did not become ready within 90s — log: {log_file}",
        file=sys.stderr,
    )
    return 1


def _create_lane_session(session: str, repo: Path, log_file: Path) -> int:
    code = _run_or_code(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session,
            "-n",
            "pipeline",
            "-c",
            str(repo),
            "exec cca --model mimo --dangerously-skip-permissions",
        ]
    )
    if code:
        return code
    quoted = shlex.quote(str(log_file))
    return _run_or_code(
        ["tmux", "pipe-pane", "-t", f"{session}:pipeline", "-o", f"cat >> {quoted}"]
    )


def main(argv: list[str]) -> int:
    vault, session = _parse_lane_args(argv)
    repo = Path(__file__).resolve().parents[1]
    os.chdir(repo)
    if _session_exists(session):
        print(
            f"launch_lane: session {session} already exists — attach: tmux attach -t {session}",
            file=sys.stderr,
        )
        return 0

    log_dir = repo / "orchestrator" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{session}.log"
    status_file = log_dir / f"{session}.status"
    log_file.write_text("", encoding="utf-8")
    code = _create_lane_session(session, repo, log_file)
    if code:
        return code

    accepted = _wait_for_accept(session)
    ready = _wait_for_ready(session, log_file)
    if ready is False:
        return 1
    if not accepted:
        print(
            "launch_lane: warning — bypass-permissions dialog not seen, may not have needed accepting",
            file=sys.stderr,
        )
    if ready is None:
        return _abort_not_ready(session, log_file)

    prompt = (
        "Use the hyperresearch-pipeline skill. "
        f"Vault tag: {vault}. Working directory: {repo}. "
        f"Run `hyperresearch run status {vault} -j` to find next_step, then drive the pipeline "
        "to completion one step at a time using the matching hyperresearch-N-* skill for each step. "
        f"Each step's procedure comes from `hyperresearch run contract {vault} <N>` "
        "(rendered; never read the raw src/hyperresearch/skills/*.md), and every subagent spawn ends "
        f"with its role brief from `hyperresearch run contract {vault} --role <role>` pasted verbatim, "
        "with absolute paths only. Verify each step's manifest transition AND output artifact content "
        "before advancing — a done status alone is not proof; read the artifact and reject placeholder/null "
        "content (null position fields, unfilled [bracket] template text, thin orphan-scan-only results), "
        "re-running the step if you find it. On database-locked errors, sleep and retry at most twice; "
        "never kill or delete the database, WAL, or lock files. When all steps are done, run "
        f"`hyperresearch run verify {vault}` then `hyperresearch run finish {vault}`. "
        f"After every step transition, append one line to {status_file} recording the step number and status."
    )
    sent = subprocess.run(
        ["tmux", "send-keys", "-t", f"{session}:pipeline", "-l", prompt],
        check=False,
    )
    if sent.returncode != 0:
        return sent.returncode or 1
    entered = subprocess.run(
        ["tmux", "send-keys", "-t", f"{session}:pipeline", "Enter"],
        check=False,
    )
    if entered.returncode != 0:
        return entered.returncode or 1
    print(f"launch_lane: {session} started for {vault} — log: {log_file}, status: {status_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
