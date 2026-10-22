"""Topic write destinations: dump vault for intermediates, one knowledge file."""

from __future__ import annotations

import sys
from pathlib import Path

from hyperresearch.core.locations import (
    HOST_DUMP_ROOT,
    HOST_KNOWLEDGE_DIR,
    knowledge_report,
    topic_report,
    topic_root,
    topic_run_dir,
    topic_slug,
    vault_tag_from_argv,
)
from hyperresearch.core.runs import init_run
from hyperresearch.core.vault import Vault


def test_topic_slug_strips_only_the_hex_suffix():
    assert topic_slug("python-testing-strategies-2d113f") == "python-testing-strategies"
    assert topic_slug("plain-slug") == "plain-slug"


def test_host_defaults_are_the_two_allowed_roots():
    assert Path("/home/monster/agentspace/dump/apps/hyperresearch") == HOST_DUMP_ROOT
    assert Path("/home/monster/agentspace/knowledge/hyperresearch") == HOST_KNOWLEDGE_DIR
    assert knowledge_report("python-testing-strategies") == (
        HOST_KNOWLEDGE_DIR / "python-testing-strategies.md"
    )


def test_override_roots_move_both_destinations(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYPERRESEARCH_DUMP_ROOT", str(tmp_path / "dump"))
    monkeypatch.setenv("HYPERRESEARCH_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    tag = "path-wire-abc123"
    assert topic_root(tag) == tmp_path / "dump" / "path-wire"
    assert topic_run_dir(tag) == tmp_path / "dump" / "path-wire" / "output" / "runs" / tag
    assert topic_report(tag).name == f"final_report_{tag}.md"
    assert knowledge_report("path-wire") == tmp_path / "knowledge" / "path-wire.md"


def test_repo_command_opens_the_dump_topic_vault(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    Vault.init(repo, name="Repo", research_dir="output")
    monkeypatch.setenv("HYPERRESEARCH_DUMP_ROOT", str(tmp_path / "dump"))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "hyperresearch.core.locations.installed_repo_root",
        lambda: repo.resolve(),
    )
    tag = "path-wire-abc123"
    monkeypatch.setattr(sys, "argv", ["hyperresearch", "run", "init", tag, "--json"])
    assert vault_tag_from_argv() == tag

    vault = Vault.discover()
    manifest = init_run(vault, tag, profile="light", query="Where do files go?\n")

    run_dir = tmp_path / "dump" / "path-wire" / "output" / "runs" / tag
    assert vault.root == (tmp_path / "dump" / "path-wire").resolve()
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "query.md").read_text(encoding="utf-8") == "Where do files go?\n"
    assert (vault.root / ".hyperresearch" / "hyperresearch.db").is_file()
    assert manifest["vault_tag"] == tag
    assert not (repo / "output" / "runs" / tag).exists()


def test_command_without_a_tag_keeps_the_discovered_vault(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    Vault.init(repo, name="Repo", research_dir="output")
    monkeypatch.setenv("HYPERRESEARCH_DUMP_ROOT", str(tmp_path / "dump"))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "hyperresearch.core.locations.installed_repo_root",
        lambda: repo.resolve(),
    )
    monkeypatch.setattr(sys, "argv", ["hyperresearch", "status"])
    vault = Vault.discover()
    assert vault.root == repo.resolve()
    assert not (tmp_path / "dump").exists() or not any((tmp_path / "dump").iterdir())
