"""Fail if a hyperresearch skill leaks into shared CLI skill dirs.

Shared CLI skill dirs may hold non-hyperresearch skills only as symlinks
from the skills SSOT (GOV_SKILLS). Hyperresearch skills stay inside this
repo under src/hyperresearch/skills/ and must never be linked there.

"The orchestrator owns /home/monster/agentspace/TASK.md and is the only writer of its Execution table."

Env overrides (tests use these; no hardcoded paths in tests):
  HR_SKILLS_DIR, SHARED_SKILL_DIRS (colon-separated), GOV_SKILLS_DIR,
  SKILL_SYMLINK_LEDGER.
"""

import csv
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_HR_SKILLS = REPO / "src" / "hyperresearch" / "skills"
DEFAULT_GOV = REPO.parents[1] / "governance_skills"
DEFAULT_LEDGER = DEFAULT_GOV / "config" / "ledgers" / "skill_symlinks.csv"
DEFAULT_SHARED = [
    Path.home() / ".agents" / "skills",
    Path.home() / ".claude" / "skills",
    Path.home() / ".codex" / "skills",
    Path.home() / ".config" / "opencode" / "skills",
    Path.home() / ".gemini" / "antigravity-cli" / "skills",
    Path.home() / ".gemini" / "config" / "skills",
    Path.home() / ".grok" / "skills",
]


def shared_dirs():
    if os.environ.get("SHARED_SKILL_DIRS"):
        return [Path(p) for p in os.environ["SHARED_SKILL_DIRS"].split(":") if p]
    ledger = Path(os.environ.get("SKILL_SYMLINK_LEDGER", str(DEFAULT_LEDGER)))
    if ledger.is_file():
        dirs = set()
        with ledger.open() as f:
            for row in csv.DictReader(f):
                if row.get("link_path"):
                    dirs.add(row["link_path"].split("/skills/")[0] + "/skills")
        if dirs:
            return sorted(Path(d) for d in dirs)
    return list(DEFAULT_SHARED)


def ledger_rows():
    ledger = Path(os.environ.get("SKILL_SYMLINK_LEDGER", str(DEFAULT_LEDGER)))
    if not ledger.is_file():
        return None
    with ledger.open() as f:
        return [r for r in csv.DictReader(f) if r.get("link_path")]


def is_hyperresearch(entry, hr_names, hr_dir):
    stem = Path(entry.name).stem
    if stem in hr_names or entry.name in hr_names or stem.startswith("hyperresearch"):
        return True
    if entry.is_symlink():
        try:
            if hr_dir in (entry.parent / os.readlink(entry)).resolve().parents:
                return True
        except OSError:
            pass
    return False


def _scan_shared_dirs(hr_names, hr_dir) -> list:
    errors = []
    for d in shared_dirs():
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir(), key=lambda p: p.name):
            if is_hyperresearch(entry, hr_names, hr_dir):
                errors.append(f"{entry}: hyperresearch skill must not be linked into shared CLI skill dirs")
    return errors


def _verify_ledger_rows(rows, gov) -> list:
    if rows is None:
        return ["skills SSOT ledger unreadable; cannot verify symlink-only rule"]
    errors = []
    for row in rows:
        if row.get("action") != "link" or not row.get("link_path"):
            continue
        link = Path(row["link_path"])
        want = Path(row["target"]) if row.get("target") else None
        if not link.is_symlink():
            errors.append(f"{link}: expected symlink from the skills SSOT, found copy or missing")
        elif not link.exists():
            errors.append(f"{link}: broken symlink (expected target under {gov})")
        elif want is not None and (link.parent / os.readlink(link)).resolve() != want.resolve():
            errors.append(f"{link}: symlink target drift: want {want}")
    return errors


def _report_placement(errors: list, rows, hr_names) -> int:
    if errors:
        print("FAIL skill placement")
        for e in errors:
            print(f"  {e}")
        return 1
    n_links = (
        len([r for r in rows if r.get("action") == "link" and r.get("link_path")]) if rows else 0
    )
    print(
        f"PASS skill placement ({len(hr_names)} hyperresearch skills contained, {n_links} SSOT links verified)"
    )
    return 0


def main():
    hr_skills = Path(os.environ.get("HR_SKILLS_DIR", str(DEFAULT_HR_SKILLS)))
    gov = Path(os.environ.get("GOV_SKILLS_DIR", str(DEFAULT_GOV))).resolve()
    hr_dir = hr_skills.resolve()
    hr_names = {p.stem for p in hr_skills.glob("hyperresearch*.md")} if hr_skills.is_dir() else set()
    errors = []
    if not hr_names:
        errors.append(f"no hyperresearch skills found in {hr_skills}")
    rows = ledger_rows()
    errors.extend(_scan_shared_dirs(hr_names, hr_dir))
    errors.extend(_verify_ledger_rows(rows, gov))
    return _report_placement(errors, rows, hr_names)


if __name__ == "__main__":
    sys.exit(main())
