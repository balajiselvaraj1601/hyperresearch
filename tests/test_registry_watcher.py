"""Watcher behavior: validate, claim, reconcile, launch, and publish.

Process calls (tmux, muse, uv) are the only fakes. Decisions stay in the script.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "registry_watcher.py"


def _load():
    spec = importlib.util.spec_from_file_location("registry_watcher", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


watcher = _load()


class Boundary:
    """Stand-in for tmux and the hyperresearch CLI."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.sessions: set[str] = set()
        self.finish_passed = True
        self.failed_check_names: list[str] = []
        self.finish_code = 0
        self.verify_code = 0

    def __call__(self, argv, cwd=None, env=None):
        command = [str(part) for part in argv]
        self.calls.append(command)
        if command[:2] == ["tmux", "list-sessions"]:
            if not self.sessions:
                return watcher.CommandResult(1, "", "no server")
            return watcher.CommandResult(0, "\n".join(sorted(self.sessions)) + "\n", "")
        if command[:2] == ["tmux", "new-session"]:
            name = command[command.index("-s") + 1]
            self.sessions.add(name)
            return watcher.CommandResult(0, "", "")
        if command[:2] == ["tmux", "kill-session"]:
            name = command[command.index("-t") + 1]
            self.sessions.discard(name)
            return watcher.CommandResult(0, "", "")
        if "vault-tag" in command:
            slug = command[command.index("vault-tag") + 1]
            body = json.dumps({"ok": True, "data": {"vault_tag": f"{slug}-abc123"}})
            return watcher.CommandResult(0, body, "")
        if "verify" in command:
            return watcher.CommandResult(self.verify_code, "", "")
        if "finish" in command:
            return watcher.CommandResult(self.finish_code, self._finish_stdout(), "")
        return watcher.CommandResult(0, "", "")

    def _finish_stdout(self) -> str:
        """Same envelope `run finish -j` writes: success wrapper, names on the manifest and checks."""
        names = [] if self.finish_passed else list(self.failed_check_names)
        checks = [{"name": name, "ok": False, "detail": name} for name in names]
        if self.finish_passed:
            checks = [{"name": "report-exists", "ok": True, "detail": "present"}]
        return json.dumps(
            {
                "ok": True,
                "data": {
                    "manifest": {
                        "status": "done" if self.finish_passed else "blocked",
                        "verify": {"passed": self.finish_passed, "failed_checks": names},
                    },
                    "verify": {"passed": self.finish_passed, "checks": checks},
                },
            }
        )


def _row(**overrides: str) -> dict:
    base = {key: "" for key in watcher.FIELDNAMES}
    base.update(
        {
            "slug": "alpha",
            "title": "Alpha",
            "prompt": "What is the ship gate?\n",
            "tier": "light",
            "priority": "1",
            "status": "pending",
        }
    )
    base.update(overrides)
    return base


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    knowledge = tmp_path / "knowledge"
    repo.mkdir()
    knowledge.mkdir()
    return repo, knowledge, knowledge / "registry.csv"


def _run(
    monkeypatch: pytest.MonkeyPatch,
    registry: Path,
    repo: Path,
    knowledge: Path,
    mode: str,
    boundary: Boundary,
) -> int:
    monkeypatch.setattr(watcher, "invoke", boundary)
    return watcher.main(
        [
            mode,
            "--registry",
            str(registry),
            "--repo",
            str(repo),
            "--knowledge",
            str(knowledge),
        ]
    )


def _rows(path: Path) -> list[dict]:
    loaded, errors = watcher.read_registry(path)
    assert errors == []
    return loaded


def _by_slug(path: Path, slug: str) -> dict:
    return next(row for row in _rows(path) if row["slug"] == slug)


def test_columns_split_input_from_watcher_state():
    assert watcher.FIELDNAMES == [
        "topic_id",
        "slug",
        "title",
        "prompt",
        "prompt_file",
        "tier",
        "priority",
        "notes",
        "runner",
        "status",
        "vault_tag",
        "output_dir",
        "session_name",
        "attempts",
        "created_at",
        "claimed_at",
        "started_at",
        "finished_at",
        "final_report",
        "error",
    ]
    assert watcher.INPUT_FIELDS.isdisjoint(watcher.ACTIVE)
    assert "status" not in watcher.INPUT_FIELDS
    assert {
        "pending",
        "claimed",
        "running",
        "verifying",
        "done",
        "failed",
        "blocked",
        "skipped",
    } == watcher.STATUSES


def test_header_only_registry_validates(tmp_path: Path):
    _repo, _knowledge, registry = _layout(tmp_path)
    watcher.write_registry(registry, [])
    assert watcher.main(["--validate", "--registry", str(registry)]) == 0


def test_blank_tier_pending_row_is_valid():
    assert watcher.validate_rows([_row(tier="")]) == []
    assert watcher.tier_of({"tier": ""}) == "light"


def test_rejects_duplicate_slugs(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    _repo, _knowledge, registry = _layout(tmp_path)
    watcher.write_registry(registry, [_row(slug="alpha"), _row(slug="alpha", title="Again")])
    assert watcher.main(["--validate", "--registry", str(registry)]) == 1
    assert "duplicate slug" in capsys.readouterr().err


def test_blank_runner_means_muse():
    assert watcher.runner_of({"runner": ""}) == "muse"
    assert watcher.runner_of({}) == "muse"
    assert tuple(watcher.WORKER_ARGV) == ("muse", "opencode")


def test_rejects_unknown_runner(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    _repo, _knowledge, registry = _layout(tmp_path)
    watcher.write_registry(registry, [_row(runner="claude")])
    assert watcher.main(["--validate", "--registry", str(registry)]) == 1
    error = capsys.readouterr().err
    assert "unknown runner" in error
    assert "claude" in error


def test_rejects_unknown_tier(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    _repo, _knowledge, registry = _layout(tmp_path)
    watcher.write_registry(registry, [_row(tier="mega")])
    assert watcher.main(["--validate", "--registry", str(registry)]) == 1
    error = capsys.readouterr().err
    assert "unknown tier" in error
    assert "mega" in error


def test_rejects_both_prompt_sources(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    _repo, _knowledge, registry = _layout(tmp_path)
    watcher.write_registry(registry, [_row(prompt_file="ask.md")])
    assert watcher.main(["--validate", "--registry", str(registry)]) == 1
    assert "prompt" in capsys.readouterr().err


def test_rejects_neither_prompt_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    _repo, _knowledge, registry = _layout(tmp_path)
    watcher.write_registry(registry, [_row(prompt="")])
    assert watcher.main(["--validate", "--registry", str(registry)]) == 1
    assert "prompt" in capsys.readouterr().err


def test_dry_run_claims_highest_priority_then_oldest_and_leaves_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    repo, knowledge, registry = _layout(tmp_path)
    watcher.write_registry(
        registry,
        [
            _row(slug="low", priority="2", created_at="2026-10-01T00:00:00+00:00"),
            _row(slug="newer", priority="10", created_at="2026-10-20T00:00:00+00:00"),
            _row(slug="older", priority="10", created_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    before = registry.read_bytes()
    code = _run(monkeypatch, registry, repo, knowledge, "--dry-run", Boundary())
    assert code == 0
    assert registry.read_bytes() == before
    assert capsys.readouterr().out == "claim older\n"


def test_dry_run_claims_nothing_while_a_row_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    repo, knowledge, registry = _layout(tmp_path)
    watcher.write_registry(
        registry,
        [
            _row(slug="live", status="running", session_name="orch-hyperresearch-live"),
            _row(slug="waiting", priority="99"),
        ],
    )
    boundary = Boundary()
    boundary.sessions.add("orch-hyperresearch-live")
    before = registry.read_bytes()
    code = _run(monkeypatch, registry, repo, knowledge, "--dry-run", boundary)
    assert code == 0
    assert registry.read_bytes() == before
    assert capsys.readouterr().out == "claim none\n"
    assert not any(command[:2] == ["tmux", "new-session"] for command in boundary.calls)


def test_stale_claim_returns_to_pending_and_does_not_block_a_newer_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    stale = (datetime.now(UTC) - timedelta(minutes=16)).isoformat()
    watcher.write_registry(
        registry,
        [
            _row(slug="stale", status="claimed", priority="1", claimed_at=stale),
            _row(slug="fresh", priority="5"),
        ],
    )
    code = _run(monkeypatch, registry, repo, knowledge, "--once", Boundary())
    assert code == 0
    released = _by_slug(registry, "stale")
    assert released["status"] == "pending"
    assert released["claimed_at"] == ""
    assert _by_slug(registry, "fresh")["status"] == "running"


def test_claim_younger_than_15_minutes_keeps_the_queue_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    fresh = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    watcher.write_registry(
        registry,
        [
            _row(slug="held", status="claimed", claimed_at=fresh, session_name=""),
            _row(slug="waiting", priority="9"),
        ],
    )
    boundary = Boundary()
    code = _run(monkeypatch, registry, repo, knowledge, "--once", boundary)
    assert code == 0
    assert _by_slug(registry, "held")["status"] == "claimed"
    assert _by_slug(registry, "waiting")["status"] == "pending"
    assert not any(command[:2] == ["tmux", "new-session"] for command in boundary.calls)


def test_reconcile_returns_a_stale_claim_before_the_queue_is_saved(tmp_path: Path):
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    stale = _row(
        status="claimed",
        claimed_at=(now - timedelta(minutes=16)).isoformat(),
        session_name="",
    )
    notes = watcher.reconcile([stale], set(), tmp_path, now)
    assert stale["status"] == "pending"
    assert notes


def test_dead_session_below_the_cap_is_pending_when_a_higher_row_is_claimed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    watcher.write_registry(
        registry,
        [
            _row(
                slug="dead",
                status="running",
                priority="1",
                attempts="0",
                session_name="orch-hyperresearch-dead",
                vault_tag="dead-abc123",
            ),
            _row(slug="next", priority="8"),
        ],
    )
    boundary = Boundary()
    code = _run(monkeypatch, registry, repo, knowledge, "--once", boundary)
    assert code == 0
    dead = _by_slug(registry, "dead")
    assert dead["status"] == "pending"
    assert dead["attempts"] == "1"
    assert _by_slug(registry, "next")["status"] == "running"
    assert [command for command in boundary.calls if "new-session" in command[:2]]


def test_dead_session_at_two_attempts_fails_and_launches_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    watcher.write_registry(
        registry,
        [
            _row(
                slug="dead",
                status="running",
                attempts="1",
                session_name="orch-hyperresearch-dead",
                vault_tag="dead-abc123",
            )
        ],
    )
    boundary = Boundary()
    code = _run(monkeypatch, registry, repo, knowledge, "--once", boundary)
    assert code == 0
    dead = _by_slug(registry, "dead")
    assert dead["status"] == "failed"
    assert dead["attempts"] == "2"
    assert "2" in dead["error"]
    assert not any(command[:2] == ["tmux", "new-session"] for command in boundary.calls)


def test_reconcile_moves_a_finished_manifest_to_verifying(tmp_path: Path):
    repo = tmp_path / "repo"
    tag = "alpha-abc123"
    run = repo / "output" / "runs" / tag
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"status": "done"}), encoding="utf-8")
    row = _row(status="running", vault_tag=tag, session_name="orch-hyperresearch-alpha")
    watcher.reconcile([row], set(), repo)
    assert row["status"] == "verifying"


def test_once_launches_one_muse_session_and_a_second_tick_launches_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    prompt = knowledge / "ask.md"
    prompt.write_text("What is the ship gate?\n", encoding="utf-8")
    watcher.write_registry(registry, [_row(slug="alpha", prompt="", prompt_file="ask.md")])
    boundary = Boundary()
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    launched = [command for command in boundary.calls if command[:2] == ["tmux", "new-session"]]
    assert len(launched) == 1
    shell = " ".join(launched[0])
    assert "muse" in shell and "exec" in shell and "--prompt-file" in shell
    for flag in ("--workspace", "--trust-workspace", "--disable-approval", "--disable-sandbox"):
        assert flag in shell
    assert "--sandbox-network" in shell and "enabled" in shell
    assert "UV_CACHE_DIR=/tmp/hyperresearch-uv-cache" in shell
    assert "orch-hyperresearch-alpha" in shell
    brief = (knowledge / "alpha" / ".work" / "brief.txt").read_text(encoding="utf-8")
    assert "What is the ship gate?\n" in brief
    assert "hyperresearch run contract" in brief
    assert "run verify" in brief
    assert "run finish" in brief
    assert "sub-orchestrators" in brief
    assert "Tier steps: 1, 2, 10, 15, 16" in brief
    assert "runner: muse" in brief
    assert "You run this topic end to end" in brief
    assert (knowledge / "alpha" / ".work" / "query.md").read_text(encoding="utf-8") == (
        "What is the ship gate?\n"
    )
    running = _by_slug(registry, "alpha")
    assert running["status"] == "running"
    assert running["session_name"] == "orch-hyperresearch-alpha"
    assert running["vault_tag"] == "alpha-abc123"
    before = registry.read_bytes()
    calls = len(boundary.calls)
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    assert [
        command for command in boundary.calls if command[:2] == ["tmux", "new-session"]
    ] == launched
    assert len(boundary.calls) > calls
    assert registry.read_bytes() == before


def test_opencode_row_launches_opencode_with_the_same_brief(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    watcher.write_registry(registry, [_row(slug="beta", runner="opencode", prompt="Cover beta.\n")])
    boundary = Boundary()
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    launched = [command for command in boundary.calls if command[:2] == ["tmux", "new-session"]]
    assert len(launched) == 1
    shell = " ".join(launched[0])
    assert "opencode" in shell and "run" in shell
    assert "--standalone" in shell and "--auto" in shell and "--file" in shell
    assert "muse" not in shell
    assert "orch-hyperresearch-beta" in shell
    assert "UV_CACHE_DIR=/tmp/hyperresearch-uv-cache" in shell
    brief = (knowledge / "beta" / ".work" / "brief.txt").read_text(encoding="utf-8")
    assert "Cover beta.\n" in brief
    assert "runner: opencode" in brief
    assert "You run this topic end to end" in brief
    assert "hyperresearch run contract" in brief
    running = _by_slug(registry, "beta")
    assert running["status"] == "running"
    assert running["runner"] == "opencode"
    assert running["session_name"] == "orch-hyperresearch-beta"


def test_live_session_name_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, knowledge, registry = _layout(tmp_path)
    watcher.write_registry(registry, [_row(slug="alpha")])
    boundary = Boundary()
    boundary.sessions.add("orch-hyperresearch-alpha")
    boundary.sessions.add("editor")
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    assert not any(command[:2] == ["tmux", "new-session"] for command in boundary.calls)
    assert not any(command[:2] == ["tmux", "kill-session"] for command in boundary.calls)
    refused = _by_slug(registry, "alpha")
    assert refused["status"] != "running"
    assert "refused" in refused["error"]
    assert "editor" in boundary.sessions


def _plant_report(repo: Path, tag: str, body: bytes) -> Path:
    report = repo / "output" / "reports" / tag / f"final_report_{tag}.md"
    run = repo / "output" / "runs" / tag
    report.parent.mkdir(parents=True)
    run.mkdir(parents=True)
    report.write_bytes(body)
    (run / "run.json").write_text(
        json.dumps({"status": "done", "profile": "light"}), encoding="utf-8"
    )
    return report


def test_publish_when_finish_passes_and_checksums_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    tag = "alpha-abc123"
    body = b"# Report\nThe ship gate passes.\n"
    source = _plant_report(repo, tag, body)
    prompt = "Ship the accepted report.\n"
    watcher.write_registry(
        registry,
        [
            _row(
                slug="alpha",
                prompt=prompt,
                status="verifying",
                vault_tag=tag,
                attempts="1",
                session_name="orch-hyperresearch-alpha",
            )
        ],
    )
    boundary = Boundary()
    boundary.sessions.update({"editor", "orch-hyperresearch-alpha"})
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    done = _by_slug(registry, "alpha")
    assert done["status"] == "done"
    assert done["final_report"].endswith("final_report.md")
    assert done["finished_at"]
    topic = knowledge / "alpha"
    assert (topic / "final_report.md").read_bytes() == source.read_bytes()
    assert watcher.hashes_match(source, topic / "final_report.md")
    assert (topic / "PROMPT.md").read_text(encoding="utf-8") == prompt
    status = (topic / "STATUS.md").read_text(encoding="utf-8")
    assert tag in status
    assert "light" in status
    assert "attempts: 1" in status
    assert f"- finished_at: {done['finished_at']}" in status
    assert str(repo / "output" / "notes" / tag) in status
    assert (topic / "PHASES.md").read_text(encoding="utf-8")
    assert (topic / "run.json").read_bytes() == (
        repo / "output" / "runs" / tag / "run.json"
    ).read_bytes()
    kills = [command for command in boundary.calls if command[:2] == ["tmux", "kill-session"]]
    assert kills == [["tmux", "kill-session", "-t", "orch-hyperresearch-alpha"]]
    assert "editor" in boundary.sessions


def test_bad_checksum_blocks_and_does_not_mark_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    tag = "alpha-abc123"
    _plant_report(repo, tag, b"vault report\n")
    watcher.write_registry(
        registry,
        [_row(slug="alpha", status="verifying", vault_tag=tag)],
    )
    monkeypatch.setattr(watcher, "hashes_match", lambda _left, _right: False)
    boundary = Boundary()
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    blocked = _by_slug(registry, "alpha")
    assert blocked["status"] == "blocked"
    assert blocked["error"] == "checksum mismatch"
    assert blocked["status"] != "done"
    assert not any(command[:2] == ["tmux", "kill-session"] for command in boundary.calls)


def test_failed_gate_blocks_with_the_failing_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    watcher.write_registry(
        registry,
        [_row(slug="alpha", status="verifying", vault_tag="alpha-abc123")],
    )
    boundary = Boundary()
    boundary.finish_passed = False
    boundary.finish_code = 1
    boundary.failed_check_names = ["report-exists", "cite-check-resolved"]
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    blocked = _by_slug(registry, "alpha")
    assert blocked["status"] == "blocked"
    assert "report-exists" in blocked["error"]
    assert "cite-check-resolved" in blocked["error"]
    assert not (knowledge / "alpha" / "PROMPT.md").exists()
    assert not (knowledge / "alpha" / "final_report.md").exists()


def test_republish_of_a_done_row_is_a_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, knowledge, registry = _layout(tmp_path)
    tag = "alpha-abc123"
    _plant_report(repo, tag, b"same bytes\n")
    watcher.write_registry(
        registry,
        [_row(slug="alpha", status="verifying", vault_tag=tag, prompt="Keep me.\n")],
    )
    boundary = Boundary()
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    finishes = sum(1 for command in boundary.calls if "finish" in command)
    prompt_path = knowledge / "alpha" / "PROMPT.md"
    prompt_path.write_text("mutated\n", encoding="utf-8")
    assert _run(monkeypatch, registry, repo, knowledge, "--once", boundary) == 0
    assert sum(1 for command in boundary.calls if "finish" in command) == finishes
    assert prompt_path.read_text(encoding="utf-8") == "mutated\n"
    assert _by_slug(registry, "alpha")["status"] == "done"


def test_finish_outcome_reads_manifest_and_check_names(tmp_path: Path):
    payload = {
        "ok": True,
        "data": {
            "manifest": {
                "status": "blocked",
                "verify": {
                    "passed": False,
                    "failed_checks": ["report-exists", "cite-check-resolved"],
                },
            },
            "verify": {
                "passed": False,
                "failed_checks": ["not-a-real-field"],
                "checks": [
                    {"name": "report-exists", "ok": False, "detail": "missing"},
                    {"name": "cite-check-resolved", "ok": False, "detail": "open"},
                    {"name": "report-length", "ok": True, "detail": "in range"},
                ],
            },
        },
    }
    passed, failed = watcher.finish_outcome(
        watcher.CommandResult(1, json.dumps(payload), ""),
        tmp_path,
        "alpha-abc123",
    )
    assert passed is False
    assert failed == ["report-exists", "cite-check-resolved"]

    checks_only = {
        "ok": True,
        "data": {
            "manifest": {"status": "blocked", "verify": {"passed": False}},
            "verify": {
                "passed": False,
                "checks": [{"name": "report-exists", "ok": False, "detail": "missing"}],
            },
        },
    }
    _passed, failed = watcher.finish_outcome(
        watcher.CommandResult(1, json.dumps(checks_only), ""),
        tmp_path,
        "alpha-abc123",
    )
    assert failed == ["report-exists"]


def test_checksum_helper_reads_the_files(tmp_path: Path):
    left = tmp_path / "a.md"
    right = tmp_path / "b.md"
    left.write_bytes(b"same")
    right.write_bytes(b"same")
    assert watcher.hashes_match(left, right)
    right.write_bytes(b"different")
    assert not watcher.hashes_match(left, right)
    status, error = watcher.publish_decision(False, False, ["report-exists"])
    assert status == "blocked"
    assert "report-exists" in error
    status, error = watcher.publish_decision(True, False, [])
    assert status == "blocked"
    assert error == "checksum mismatch"


def test_default_registry_lives_under_knowledge_hyperresearch():
    assert watcher.DEFAULT_REGISTRY.name == "registry.csv"
    assert watcher.DEFAULT_REGISTRY.parent.name == "hyperresearch"
    assert watcher.DEFAULT_REGISTRY.parent.parent.name == "knowledge"
