"""Tests for hook installer and skill file provisioning (hyperresearch roster)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess

import pytest

from hyperresearch.core.hooks import (
    _RETIRED_AGENT_FILES,
    _RETIRED_SKILL_DIRS,
    _install_claude_hook,
    _install_hyperresearch_skill,
    _prune_retired_agents,
    _write_hook_script,
    install_hooks,
)

# ---------------------------------------------------------------------------
# Entry skill — installs at /hyperresearch only (v0.8.1+)
# ---------------------------------------------------------------------------


def test_install_hyperresearch_skill_creates_nothing(tmp_vault):
    """The entry skill is retired as of v8. There is no router SKILL.md and no
    `/hyperresearch` slash command; pipeline steps run via the external
    `hyperresearch-runner` agent. Regression guard: the skill must not return.
    """
    result = _install_hyperresearch_skill(tmp_vault.root)
    assert result is None

    assert not (tmp_vault.root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert not (tmp_vault.root / ".claude" / "skills" / "research" / "SKILL.md").exists()


# ---------------------------------------------------------------------------
# Retired-roster pruning
# ---------------------------------------------------------------------------


def test_prune_retired_agents_removes_old_files(tmp_vault):
    """Pre-hyperresearch vaults have analyst/auditor/rewriter/subrun/merger agent
    files and a research-ensemble skill dir. Installing onto such a vault
    must prune those so the installed state matches the current architecture."""
    agents_dir = tmp_vault.root / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for name in _RETIRED_AGENT_FILES:
        (agents_dir / name).write_text("pre-hyperresearch content\n", encoding="utf-8")

    skills_dir = tmp_vault.root / ".claude" / "skills"
    for name in _RETIRED_SKILL_DIRS:
        retired_skill = skills_dir / name
        retired_skill.mkdir(parents=True, exist_ok=True)
        # What we actually shipped into these dirs: the entry skill, renamed.
        # Every version of it named the project in its body.
        (retired_skill / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n\n# Deep research\n\nRun the hyperresearch pipeline.\n",
            encoding="utf-8",
        )

    result = _prune_retired_agents(tmp_vault.root)
    assert result is not None
    assert "Pruned retired" in result

    for name in _RETIRED_AGENT_FILES:
        assert not (agents_dir / name).exists(), f"{name} still present"
    for name in _RETIRED_SKILL_DIRS:
        assert not (skills_dir / name).exists(), f"skill dir {name} still present"


def test_prune_retired_agents_noop_on_clean_vault(tmp_vault):
    """On a fresh vault, prune is a no-op."""
    result = _prune_retired_agents(tmp_vault.root)
    assert result is None


def test_prune_retired_agents_spares_a_users_own_research_skill(tmp_vault):
    """`research` is an obvious name for a hand-written personal skill, and on a
    --global install the prune runs against ~/.claude/skills/. Deleting on name
    alone destroyed user content that was never ours (#73)."""
    skills_dir = tmp_vault.root / ".claude" / "skills"
    mine = skills_dir / "research"
    mine.mkdir(parents=True, exist_ok=True)
    (mine / "SKILL.md").write_text(
        "---\nname: research\ndescription: My own literature workflow\n---\n\nStep 1...\n",
        encoding="utf-8",
    )
    (mine / "reference.md").write_text("notes I wrote\n", encoding="utf-8")

    result = _prune_retired_agents(tmp_vault.root)

    assert (mine / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: research")
    assert (mine / "reference.md").exists()
    # And the user is told it was left behind, rather than it happening silently.
    assert result is not None
    assert "Left alone (not ours)" in result
    assert ".claude/skills/research" in result


def test_prune_retired_agents_spares_a_dir_with_no_skill_file(tmp_vault):
    """No SKILL.md means we have no evidence it was ever ours, so leave it."""
    skills_dir = tmp_vault.root / ".claude" / "skills"
    mine = skills_dir / "research"
    mine.mkdir(parents=True, exist_ok=True)
    (mine / "scratch.txt").write_text("something\n", encoding="utf-8")

    _prune_retired_agents(tmp_vault.root)

    assert (mine / "scratch.txt").exists()


# ---------------------------------------------------------------------------
# PreToolUse hook — the reminder must reach the model (#94)
# ---------------------------------------------------------------------------


def test_installed_hook_delivers_reminder_through_the_injection_channel(tmp_vault):
    """Exit 0 + hookSpecificOutput JSON on stdout is the only channel that
    reaches the model. stderr at exit 0 is written to the debug log, so a hook
    that writes the reminder there has no effect at all."""
    script = _write_hook_script(tmp_vault.root, "hyperresearch").read_text(encoding="utf-8")

    assert "hookSpecificOutput" in script
    assert "hookEventName: 'PreToolUse'" in script
    assert "additionalContext" in script
    assert "process.stderr.write" not in script


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_installed_hook_emits_parseable_injection_json(tmp_vault):
    """Run the installed script the way Claude Code does, and read the channel
    the model reads."""
    hook_path = _write_hook_script(tmp_vault.root, "hyperresearch")

    proc = subprocess.run(
        ["node", str(hook_path)],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_vault.root)},
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    output = json.loads(proc.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert "HYPERRESEARCH" in output["additionalContext"]
    assert "hyperresearch fetch" in output["additionalContext"]


# ---------------------------------------------------------------------------
# install_hooks — end-to-end integration
# ---------------------------------------------------------------------------


def test_install_hooks_registers_full_hyperresearch_roster(tmp_vault):
    """install_hooks wires the hook, the entry skill, and prunes retired agents.
    The 16-agent fleet and step skills are retired as of v8; pipeline steps run
    via the external `hyperresearch-runner` agent."""
    actions = install_hooks(tmp_vault.root, "hyperresearch")
    assert actions  # something happened

    # NO agent files should be created (fleet retired)
    agents_dir = tmp_vault.root / ".claude" / "agents"
    if agents_dir.exists():
        actual_agents = {p.name for p in agents_dir.iterdir() if p.is_file()}
        assert actual_agents == set(), f"Unexpected agent files: {actual_agents}"

    # Entry skill retired too — no router SKILL.md, no /hyperresearch command
    assert not (tmp_vault.root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert not (tmp_vault.root / ".claude" / "skills" / "research" / "SKILL.md").exists()

    # Hook settings written
    assert (tmp_vault.root / ".claude" / "settings.json").exists()
    assert (tmp_vault.root / ".hyperresearch" / "hook.js").exists()

    # Prune action should have run (even if no-op on clean vault)
    # Verify no retired agent files remain
    for name in _RETIRED_AGENT_FILES:
        assert not (tmp_vault.root / ".claude" / "agents" / name).exists()


def test_install_hooks_second_run_is_noop(tmp_vault):
    first = install_hooks(tmp_vault.root, "hyperresearch")
    assert first
    second = install_hooks(tmp_vault.root, "hyperresearch")
    # Hook installer may still report the hook is already installed → no
    # actions or a trivial subset. Must not crash, must not reinstall files.
    assert not second or all("pruned" not in a.lower() for a in second)


# ---------------------------------------------------------------------------
# The registered command must survive the shell that runs it
# ---------------------------------------------------------------------------


def test_installed_hook_command_keeps_the_script_path_in_one_argument(tmp_path):
    """Claude Code runs a hook command through a shell, so an unquoted path is
    split at its first space and node receives a truncated script path. Project
    directories with spaces are ordinary — a Windows user directory, or anything
    under "My Documents" — and the hook then fails on every matching tool call
    without the reminder ever appearing."""
    project = tmp_path / "my project"
    project.mkdir()

    _install_claude_hook(project, "hyperresearch")

    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    assert shlex.split(command) == ["node", (project / ".hyperresearch" / "hook.js").as_posix()]
