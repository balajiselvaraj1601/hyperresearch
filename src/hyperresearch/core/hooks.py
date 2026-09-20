"""Agent hook installer — installs the Claude Code PreToolUse hook, skills, and subagents.

The hook reminds Claude Code to check the research base before doing raw web
searches. The `/hyperresearch` skill drives the research
protocol. The hyperresearch subagents (fetcher, loci-analyst, depth-investigator,
four critics, patcher, polish-auditor) are Claude Code registered agents
spawned via the Task tool.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Prompt rendering — skill files and agent prompt bodies are Jinja templates
# (custom << >> delimiters; see core/render.py). The active render context is
# process-global state set by install_hooks()/install_global_hooks() before
# the installers run; direct calls to individual _install_* helpers (tests)
# fall back to a default full-profile context lazily.
# ---------------------------------------------------------------------------
_RENDER_STATE: dict | None = None


def _set_render_state(profile_name: str, config_path: Path | None) -> None:
    global _RENDER_STATE
    from hyperresearch.core.render import build_render_context

    _RENDER_STATE = {
        "profile_name": profile_name,
        "context": build_render_context(config_path, primary=profile_name),
    }


def _get_render_state() -> dict:
    if _RENDER_STATE is None:
        _set_render_state("full", None)
    assert _RENDER_STATE is not None
    return _RENDER_STATE


def _render_installed(content: str) -> str:
    """Render a prompt template and stamp the provenance header."""
    from hyperresearch import __version__
    from hyperresearch.core.render import insert_after_frontmatter, render_header, render_prompt

    state = _get_render_state()
    rendered = render_prompt(content, state["context"])
    header = render_header(state["profile_name"], __version__)
    return insert_after_frontmatter(rendered, header)


# Scaffold-only section headers that must NEVER appear in a final_report draft.
# Used by critic agents (as detection patterns), the polish auditor, and the
# `wrapper-report` lint rule. Single canonical source of truth so prompts +
# lint stay in sync.
#
# Matching is prefix-based on the header line — this way the list tolerates
# both em-dash and ASCII-dash variants (`(VERBATIM — gospel)` vs
# `(VERBATIM -- gospel)`), extra whitespace, and suffix variants.
#
# NOTE: `## Core tension` is intentionally omitted. The scaffold uses it as a
# bullet-list planning section, but the drafting conventions also allow it as
# a legitimate opening paragraph of the body. Leaking the planning version is
# a real problem, but header-match alone can't distinguish the two.
SCAFFOLD_ONLY_SECTION_HEADERS: tuple[str, ...] = (
    "## User Prompt (VERBATIM",
    "## Canonical research query source",
    "## Session wrapper requirements",
    "## What the user explicitly asked for",
    "## Prompt decomposition",
    "## Primary activity and secondary flavor",
    "## The structural plan",
    "## Where each source will land",
    "## Citation budget",
    "## Coverage checklist",
)


def _render_scaffold_only_bullets(indent: str = "   ") -> str:
    """Render SCAFFOLD_ONLY_SECTION_HEADERS as an indented bullet list for
    injection into agent prompts. Keeps the canonical source of truth in code.
    """
    return "\n".join(f"{indent}- `{h} ...`" for h in SCAFFOLD_ONLY_SECTION_HEADERS)


def install_hooks(
    vault_root: Path,
    hpr_path: str = "hyperresearch",
    profile: str = "full",
) -> list[str]:
    """Install the Claude Code hook + skills + subagents. Returns list of actions taken.

    Skill and agent prompts are rendered from the given pipeline profile
    (plus any `[profile.*]` overlays in the vault's config.toml).

    Hyperresearch roster (as of v8): the 16-agent fleet and step skills are retired;
    a single external `hyperresearch-runner` agent loads step contracts from
    `src/hyperresearch/skills/` at execution time.
    """
    config_path = vault_root / ".hyperresearch" / "config.toml"
    _set_render_state(profile, config_path if config_path.exists() else None)
    actions = []

    for installer in (
        lambda: _install_claude_hook(vault_root, hpr_path),
        lambda: _install_hyperresearch_skill(vault_root),
        lambda: _prune_retired_agents(vault_root),
    ):
        result = installer()
        if result:
            actions.append(result)

    return actions


def install_global_hooks(
    home: Path | None = None,
    hpr_path: str = "hyperresearch",
    profile: str = "full",
) -> list[str]:
    """Install Claude Code skills + agents globally under ~/.claude/.

    Unlike `install_hooks`, this skips:
      - The PreToolUse vault-check hook (don't want it firing on every
        Claude Code session, only ones that have a hyperresearch vault)
      - Vault init (handled per-project, on first /hyperresearch invocation)
      - CLAUDE.md injection (per-project)
      - The 16 agent fleet and step skills. These are retired as of v8;
        pipeline steps run via the external `hyperresearch-runner` agent
        which loads step contracts from `src/hyperresearch/skills/` at
        execution time.

    The result: pip install + this once, and `/hyperresearch` is available
    in every Claude Code session anywhere on the machine. The vault,
    output/, and CLAUDE.md materialize in the project root where Claude
    Code is running, on first invocation.

    Also prunes any hyperresearch-N-* step-skill dirs left in ~/.claude/skills/
    by older versions (≤0.8.2 used to install step skills globally).
    """
    if home is None:
        home = Path.home()

    # Global installs have no vault config — built-in profiles only.
    _set_render_state(profile, None)
    actions = []

    for installer in (
        lambda: _install_hyperresearch_skill(home),
        lambda: _prune_retired_agents(home),
        lambda: _prune_global_step_skills(home),
    ):
        result = installer()
        if result:
            actions.append(result)

    return actions


def _prune_global_step_skills(home: Path) -> str | None:
    """Remove hyperresearch-N-* step skill dirs from ~/.claude/skills/.

    Used by install_global_hooks to clean up after older versions (≤0.8.2)
    that installed step skills globally. Step skills now live per-project.
    """
    skills_root = home / ".claude" / "skills"
    if not skills_root.is_dir():
        return None

    pruned: list[str] = []
    for child in skills_root.iterdir():
        if not child.is_dir():
            continue
        # Match hyperresearch-<digit>-* (the 16 step skills) but not
        # the entry skill at .claude/skills/hyperresearch/
        name = child.name
        if not name.startswith("hyperresearch-"):
            continue
        suffix = name[len("hyperresearch-") :]
        if not suffix or not suffix[0].isdigit():
            continue
        if not _is_our_skill_dir(child):
            continue
        _remove_skill_dir(child)
        pruned.append(name)

    if not pruned:
        return None
    return f"Pruned {len(pruned)} global step-skill dirs (now per-project): {', '.join(pruned[:3])}{'...' if len(pruned) > 3 else ''}"


HOOK_SCRIPT_TEMPLATE = """\
#!/usr/bin/env node
/**
 * hyperresearch PreToolUse hook — reminds agent to check research base first.
 * Installed by: hyperresearch install
 */
const fs = require('fs');
const path = require('path');

const HPR = '{hpr_path}';

// Check if a .hyperresearch directory exists (vault is initialized)
function findVault() {{
    let dir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
    while (true) {{
        if (fs.existsSync(path.join(dir, '.hyperresearch'))) return dir;
        const parent = path.dirname(dir);
        if (parent === dir) return null;
        dir = parent;
    }}
}}

const vault = findVault();
if (vault) {{
    const msg = [
        'HYPERRESEARCH: A research knowledge base exists in this project.',
        '',
        'BEFORE searching the web, check existing research:',
        '  ' + HPR + ' search "<your query>" -j',
        '',
        'DO NOT use WebFetch for source pages. Use hyperresearch fetch instead:',
        '  ' + HPR + ' fetch "<url>" --tag <topic> -j',
        'It runs a real headless browser, saves full content + screenshot, and indexes for future sessions.',
        '',
        'After fetching, READ the content and FOLLOW LINKS to primary sources. Keep fetching until you have the real sources, not just summaries.',
        '',
        'For multiple URLs, use subagents to fetch in parallel.',
    ].join('\\n');
    // stderr reaches the model only on exit 2. On exit 0 it goes to the debug
    // log, so the reminder has to leave as hookSpecificOutput JSON on stdout.
    process.stdout.write(JSON.stringify({{
        hookSpecificOutput: {{
            hookEventName: 'PreToolUse',
            additionalContext: msg
        }}
    }}) + '\\n');
}}
"""


def _write_hook_script(vault_root: Path, hpr_path: str) -> Path:
    """Write the hook JS script to .hyperresearch/hook.js."""
    hook_dir = vault_root / ".hyperresearch"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hook_dir / "hook.js"
    js_path = hpr_path.replace("\\", "\\\\")
    hook_path.write_text(HOOK_SCRIPT_TEMPLATE.format(hpr_path=js_path), encoding="utf-8")
    return hook_path


def _install_claude_hook(vault_root: Path, hpr_path: str) -> str | None:
    """Install PreToolUse hook into .claude/settings.json."""
    hook_path = _write_hook_script(vault_root, hpr_path)

    settings_dir = vault_root / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_path = settings_dir / "settings.json"

    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    hooks = settings.setdefault("hooks", {})
    pre_tool = hooks.setdefault("PreToolUse", [])

    for entry in pre_tool:
        if isinstance(entry, dict):
            for h in entry.get("hooks", []):
                if "hyperresearch" in h.get("command", ""):
                    return None

    # Web tools only. The reminder is "check the vault before you search the
    # web"; on Glob and Grep it is noise, and now that the payload actually
    # reaches the model (it was silently discarded before #94), every match
    # costs context on every call.
    pre_tool.append(
        {
            "matcher": "WebSearch|WebFetch",
            "hooks": [
                {
                    "type": "command",
                    "command": f'node "{hook_path.as_posix()}"',
                }
            ],
        }
    )

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return "Claude Code: .claude/settings.json (PreToolUse hook)"


WORKER_SAFETY_GUARD = """\
## Infrastructure errors — never self-remediate destructively

If a tool, CLI, or database call fails (for example "database is locked",
a lock timeout, or contention from parallel siblings), NEVER run
destructive system-level commands to self-resolve: no `kill`, no `kill -9`,
no `pkill`, no recursive force-delete, and no deleting database, WAL, or
lock files. Retry the failing command at most twice with a short `sleep`
between attempts. If it still fails, note the blocker in your final reply
and stop that line of work. The orchestrator has broader context and safer
recovery options (for example a WAL checkpoint). Destructive self-recovery
is a security incident, not a fix.
"""


_RETIRED_AGENT_FILES: tuple[str, ...] = (
    "hyperresearch-analyst.md",
    "hyperresearch-auditor.md",
    "hyperresearch-rewriter.md",
    "hyperresearch-subrun.md",
    "hyperresearch-merger.md",
)

_RETIRED_SKILL_DIRS: tuple[str, ...] = (
    "research-ensemble",
    "research-layercake",  # superseded by /hyperresearch alias
    "research",  # /research alias retired in v0.8.1 — only /hyperresearch now
)

# Every SKILL.md this project has ever installed names the project in its
# frontmatter or its body. The retired dirs predate any install marker, so a
# marker file cannot be used to recognize them — the content we shipped is the
# only evidence available after the fact.
_OWNED_SKILL_MARKERS: tuple[str, ...] = ("hyperresearch", "layercake")


def _is_our_skill_dir(path: Path) -> bool:
    """True when `path` holds a SKILL.md this project wrote.

    A name match alone is not license to delete a directory. `research` is an
    ordinary English word and an obvious name for a hand-written personal
    skill, and `--global` puts the prune in ~/.claude/skills/, which is shared
    across every project the user has. Deleting on name alone destroyed user
    content that was never ours (#73).
    """
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        return False
    try:
        text = skill_file.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(marker in text for marker in _OWNED_SKILL_MARKERS)


def _remove_skill_dir(path: Path) -> None:
    """Delete a skill directory and everything under it."""
    import shutil

    shutil.rmtree(path)


# V1 modality files — left over inside .claude/skills/hyperresearch/ on
# vaults that were installed before the V8 alias-based entry skill.
_RETIRED_HYPERRESEARCH_FILES: tuple[str, ...] = (
    "SKILL-collect.md",
    "SKILL-synthesize.md",
    "SKILL-compare.md",
    "SKILL-forecast.md",
)


def _prune_retired_agents(vault_root: Path) -> str | None:
    """Delete agent files + skill dirs from the pre-hyperresearch roster.

    Running this on a fresh vault is a no-op. On an upgraded vault, it removes
    retired agent .md files and the old /research-ensemble + /research-layercake
    skill dirs so the installed state matches the current architecture.

    A retired skill dir is only removed when its SKILL.md is recognizably one
    we shipped. Anything else with the same name belongs to the user and is
    reported instead of deleted.
    """
    pruned: list[str] = []
    kept: list[str] = []

    agents_dir = vault_root / ".claude" / "agents"
    if agents_dir.exists():
        for name in _RETIRED_AGENT_FILES:
            p = agents_dir / name
            if p.exists():
                p.unlink()
                pruned.append(f"agent {name}")

    skills_dir = vault_root / ".claude" / "skills"
    if skills_dir.exists():
        for name in _RETIRED_SKILL_DIRS:
            p = skills_dir / name
            if not p.is_dir():
                continue
            if not _is_our_skill_dir(p):
                kept.append(name)
                continue
            _remove_skill_dir(p)
            pruned.append(f"skill dir {name}")

        # V1 modality files (SKILL-collect.md etc.) left inside the
        # /hyperresearch skill dir from the old multi-file install layout.
        hpr_dir = skills_dir / "hyperresearch"
        if hpr_dir.is_dir():
            for name in _RETIRED_HYPERRESEARCH_FILES:
                p = hpr_dir / name
                if p.exists():
                    p.unlink()
                    pruned.append(f"file hyperresearch/{name}")

    parts: list[str] = []
    if pruned:
        parts.append("Pruned retired: " + ", ".join(pruned))
    if kept:
        parts.append("Left alone (not ours): " + ", ".join(f".claude/skills/{n}" for n in kept))
    if not parts:
        return None
    return " | ".join(parts)


def _read_skill_source(src_name: str) -> str | None:
    """Read a skill file from package resources, falling back to source tree."""
    import importlib.resources

    try:
        return (
            importlib.resources.files("hyperresearch.skills")
            .joinpath(src_name)
            .read_text(encoding="utf-8")
        )
    except Exception:
        skill_src = Path(__file__).parent.parent / "skills" / src_name
        if skill_src.exists():
            return skill_src.read_text(encoding="utf-8")
        return None


def _install_hyperresearch_skill(vault_root: Path) -> str | None:
    """Retired no-op. The entry skill is never installed.

    Through v7 this wrote `.claude/skills/hyperresearch/SKILL.md`, whose
    `name: hyperresearch` frontmatter registered the `/hyperresearch`
    slash command. As of v8 there is no router skill and no slash command:
    the external `hyperresearch-runner` agent reads step contracts straight
    from `src/hyperresearch/skills/` and runs one step per invocation.

    Kept as a no-op rather than deleted so any remaining caller is harmless.
    Returns None always.
    """
    return None


_HYPERRESEARCH_STEP_SKILLS = [
    "hyperresearch-1-decompose",
    "hyperresearch-1-5-chapter-partition",
    "hyperresearch-2-width-sweep",
    "hyperresearch-3-contradiction-graph",
    "hyperresearch-4-loci-analysis",
    "hyperresearch-5-depth-investigation",
    "hyperresearch-6-cross-locus-reconcile",
    "hyperresearch-7-source-tensions",
    "hyperresearch-8-corpus-critic",
    "hyperresearch-9-evidence-digest",
    "hyperresearch-10-triple-draft",
    "hyperresearch-11-synthesize",
    "hyperresearch-12-critics",
    "hyperresearch-13-gap-fetch",
    "hyperresearch-14-patcher",
    "hyperresearch-14-5-cite-check",
    "hyperresearch-15-polish",
    "hyperresearch-16-readability-audit",
]


def _step_id_of_skill(skill_name: str) -> str:
    """`hyperresearch-14-5-cite-check` -> "14.5"; `hyperresearch-2-width-sweep` -> "2".

    The step id is the run of leading numeric segments after the
    `hyperresearch-` prefix, joined with dots — the same key `hpr run step`
    records in the manifest.
    """
    parts = skill_name.removeprefix("hyperresearch-").split("-")
    digits: list[str] = []
    for part in parts:
        if not part.isdigit():
            break
        digits.append(part)
    return ".".join(digits)


# Step id -> installed skill slug, derived from the roster above so
# `hpr run resume` can never suggest a skill the installer doesn't ship.
STEP_SKILL_BY_ID: dict[str, str] = {
    _step_id_of_skill(name): name for name in _HYPERRESEARCH_STEP_SKILLS
}


def step_skill_slug(step: str | None) -> str | None:
    """The installed skill slug for a manifest step id, or None if unknown."""
    if step is None:
        return None
    return STEP_SKILL_BY_ID.get(str(step))


def _install_hyperresearch_step_skills(vault_root: Path) -> str | None:
    """Retired no-op. Step skills are never installed.

    Through v7 this wrote 18 `.claude/skills/hyperresearch-N-name/SKILL.md`
    directories. As of v8 the step contracts are read straight from
    `src/hyperresearch/skills/` by the external `hyperresearch-runner` agent,
    one step per invocation, so nothing needs to land in a project's skill
    directory. Installing them again would re-advertise 18 internal steps to
    every Claude Code session.

    Kept as a no-op rather than deleted so any remaining caller is harmless.
    Returns None always.
    """
    return None


def _install_hyperresearch_step_skills_retired_impl(vault_root: Path) -> str | None:
    """Dead pre-v8 body, retained for reference only. Never called."""
    skills_root = vault_root / ".claude" / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    expected = set(_HYPERRESEARCH_STEP_SKILLS)
    installed: list[str] = []
    pruned: list[str] = []

    for skill_name in _HYPERRESEARCH_STEP_SKILLS:
        src_name = f"{skill_name}.md"
        content = _read_skill_source(src_name)
        if content is None:
            continue
        content = _render_installed(content)

        skill_dir = skills_root / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        dest_path = skill_dir / "SKILL.md"

        if dest_path.exists() and dest_path.read_text(encoding="utf-8") == content:
            continue

        dest_path.write_text(content, encoding="utf-8")
        installed.append(skill_name)

    # Prune stale skill dirs: any hyperresearch-* not in current roster, plus
    # any leftover layercake-* dirs from the pre-rename install layout.
    for child in skills_root.iterdir():
        if not child.is_dir():
            continue
        is_stale_hpr = child.name.startswith("hyperresearch-") and child.name not in expected
        is_legacy_layercake = child.name.startswith("layercake-")
        if not (is_stale_hpr or is_legacy_layercake):
            continue
        if not _is_our_skill_dir(child):
            continue
        _remove_skill_dir(child)
        pruned.append(child.name)

    if not installed and not pruned:
        return None

    parts: list[str] = []
    if installed:
        parts.append(f"{len(installed)} step skills: {', '.join(installed)}")
    if pruned:
        parts.append(f"pruned: {', '.join(pruned)}")
    return f"Claude Code: .claude/skills/hyperresearch-N-*/SKILL.md ({'; '.join(parts)})"
