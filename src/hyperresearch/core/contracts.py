"""Render step contracts and role briefs for a live run.

`src/hyperresearch/skills/hyperresearch-N-*.md` (step contracts) and
`src/hyperresearch/skills/roles/<role>.md` (subagent role briefs) are Jinja
templates with `<< p.x >>` profile placeholders, `$HPR` for the CLI path and
run-relative `output/runs/<vault_tag>/...` paths. Until v8 the installer
rendered them into `.claude/`; the runner now reads them at execution time,
so this module is the single render path. Rendering resolves:

- profile placeholders from the vault's configured profile (`<< p.x >>`)
- `$HPR` to the absolute CLI executable
- `<vault_tag>` to the run's tag
- `output/runs/<tag>` and `output/notes` to absolute paths, because
  subagents run with their own cwd and have written run artifacts to the
  workspace root when handed relative paths (two lanes, 2026-09-18)
"""

from __future__ import annotations

import importlib.resources
import re
from pathlib import Path

ROLES_DIR = "roles"

# `output/runs/<tag>/x`, `output/notes/x` — the run-relative paths that step
# contracts and role briefs use; both are rewritten to absolute paths.
_RUN_RELATIVE_PATH_RE = re.compile(r"(?<![\w/.-])output/(runs|notes|reports)(?=[/\s`'\")\]]|$)")


class ContractError(Exception):
    pass


def _skills_root() -> Path:
    try:
        return Path(str(importlib.resources.files("hyperresearch.skills")))
    except Exception:  # pragma: no cover - source-tree fallback
        return Path(__file__).parent.parent / "skills"


def list_roles() -> list[str]:
    roles_dir = _skills_root() / ROLES_DIR
    if not roles_dir.is_dir():
        return []
    return sorted(p.stem for p in roles_dir.glob("*.md"))


def _read(relative: str) -> str:
    path = _skills_root() / relative
    if not path.is_file():
        raise ContractError(f"no such contract: {relative}")
    return path.read_text(encoding="utf-8")


def _step_contract_name(step: str) -> str:
    from hyperresearch.core.hooks import step_skill_slug

    slug = step_skill_slug(step)
    if slug is None:
        raise ContractError(f"unknown step id '{step}'")
    return f"{slug}.md"


def _absolutise(text: str, research_dir: Path) -> str:
    root = str(research_dir).replace("\\", "/")
    return _RUN_RELATIVE_PATH_RE.sub(lambda m: f"{root}/{m.group(1)}", text)


def render_contract(
    vault,
    vault_tag: str,
    step: str | None = None,
    role: str | None = None,
    hpr_path: str | None = None,
) -> str:
    """Render one step contract or one role brief for `vault_tag`.

    Exactly one of `step` / `role` must be given. The profile used for
    `<< p.x >>` is the run manifest's profile, falling back to the vault's
    configured pipeline profile.
    """
    from hyperresearch.core.agent_docs import _resolve_executable
    from hyperresearch.core.render import build_render_context, render_prompt
    from hyperresearch.core.runs import RunError, load_manifest

    if (step is None) == (role is None):
        raise ContractError("give exactly one of step or role")

    relative = f"{ROLES_DIR}/{role}.md" if role else _step_contract_name(str(step))
    template = _read(relative)

    try:
        profile = load_manifest(vault, vault_tag).get("profile") or "full"
    except RunError as e:
        raise ContractError(str(e)) from e

    rendered = render_prompt(template, build_render_context(vault.config_path, primary=profile))
    rendered = rendered.replace("$HPR", hpr_path or _resolve_executable())
    rendered = rendered.replace("<vault_tag>", vault_tag)
    return _absolutise(rendered, vault.research_dir)
