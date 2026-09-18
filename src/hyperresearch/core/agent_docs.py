"""Agent documentation integration — inject the hyperresearch blurb into CLAUDE.md.

hyperresearch is a Claude Code harness. This module writes/updates CLAUDE.md
at the vault root so Claude Code auto-loads the research workflow on every
session. Pre-existing AGENTS.md / GEMINI.md / .github/copilot-instructions.md
files (from older hyperresearch vaults or other tools) are left alone — we
don't delete user content, but we no longer generate them either.
"""

from __future__ import annotations

import re
from pathlib import Path

HYPERRESEARCH_SECTION_MARKER = "<!-- hyperresearch:start -->"
HYPERRESEARCH_SECTION_END = "<!-- hyperresearch:end -->"

HYPERRESEARCH_BLURB = """
{marker}
## Research Base (hyperresearch)

**CLI: `{hpr}`** — use this path for every hyperresearch command.

Pipeline work runs through the `hyperresearch-runner` agent, one step per
invocation. It reads each step contract from the hyperresearch package's
`skills/` directory at execution time. There is no router skill, no
`hyperresearch-*` step skills, and no `/hyperresearch` slash command.

Do **not** WebFetch research pages — use `{hpr} fetch`.
`{hpr} run status -j` / `resume -j` report the next step; hand that step to
`hyperresearch-runner`.
{end_marker}
"""


def _resolve_executable() -> str:
    """Find the absolute path to the hyperresearch executable.

    Priority: venv sibling of current python > PATH > bare name.
    """
    import shutil
    import sys

    # First: find it relative to the current Python interpreter (venv installs).
    # This takes priority over PATH to avoid picking up a system-wide install.
    python_dir = Path(sys.executable).parent
    for name in ("hyperresearch", "hyperresearch.exe"):
        candidate = python_dir / name
        if candidate.exists():
            return str(candidate)
    # Also check Scripts/ subdirectory (Windows venv layout)
    for name in ("hyperresearch", "hyperresearch.exe"):
        candidate = python_dir / "Scripts" / name
        if candidate.exists():
            return str(candidate)

    # Second: check PATH
    which = shutil.which("hyperresearch")
    if which:
        return which

    # Fallback — bare name, hope it's on PATH
    return "hyperresearch"


def inject_agent_docs(vault_root: Path) -> list[str]:
    """Inject hyperresearch docs into CLAUDE.md at the vault root.

    Always writes/updates CLAUDE.md. Does NOT touch AGENTS.md, GEMINI.md,
    or .github/copilot-instructions.md — hyperresearch is a Claude Code
    harness now, not a multi-platform tool. Pre-existing non-Claude doc
    files are left untouched (we don't delete user content), but no new
    ones are created.
    """
    hpr_path = _resolve_executable()
    # Use forward slashes — bash on Windows eats backslashes
    hpr_path = hpr_path.replace("\\", "/")
    # No date interpolation here: a `Today is YYYY-MM-DD` line in the
    # cached prefix would bust Claude Code's prompt cache once per day.
    blurb = HYPERRESEARCH_BLURB.format(
        marker=HYPERRESEARCH_SECTION_MARKER,
        end_marker=HYPERRESEARCH_SECTION_END,
        hpr=hpr_path,
    )

    modified: list[str] = []
    result = _inject_into_file(vault_root / "CLAUDE.md", blurb, "CLAUDE.md")
    if result:
        modified.append(result)
    return modified


def _inject_into_file(filepath: Path, blurb: str, filename: str) -> str | None:
    """Inject the hyperresearch blurb into a single file. Returns action taken or None."""
    if filepath.exists():
        content = filepath.read_text(encoding="utf-8-sig")

        if HYPERRESEARCH_SECTION_MARKER in content:
            pattern = re.compile(
                re.escape(HYPERRESEARCH_SECTION_MARKER)
                + r".*?"
                + re.escape(HYPERRESEARCH_SECTION_END),
                re.DOTALL,
            )
            new_content = pattern.sub(lambda _: blurb.strip(), content)
            if new_content != content:
                filepath.write_text(new_content, encoding="utf-8")
                return f"{filename} (updated)"
            return None
        else:
            separator = "\n\n" if not content.endswith("\n") else "\n"
            filepath.write_text(content + separator + blurb.strip() + "\n", encoding="utf-8")
            return f"{filename} (appended)"
    else:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        header = f"# {filepath.stem}\n"
        filepath.write_text(header + blurb.strip() + "\n", encoding="utf-8")
        return f"{filename} (created)"
