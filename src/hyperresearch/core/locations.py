"""Where a topic may write on this host.

Intermediates for a task slug live under the dump topic directory. The
accepted report is one markdown file under the knowledge directory. Tests
override either root with ``HYPERRESEARCH_DUMP_ROOT`` or
``HYPERRESEARCH_KNOWLEDGE_DIR``.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

HOST_DUMP_ROOT = Path("/home/monster/agentspace/dump/apps/hyperresearch")
HOST_KNOWLEDGE_DIR = Path("/home/monster/agentspace/knowledge/hyperresearch")

_SUFFIX = re.compile(r"-([0-9a-f]{6})$")
_ARG_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}-[0-9a-f]{6}$")
_TAG_FLAGS = frozenset({"--tag", "--run", "--vault-tag"})


def installed_repo_root() -> Path:
    """Checkout that contains this package."""
    return Path(__file__).resolve().parents[3]


def dump_root() -> Path:
    """Directory that holds one subdirectory per task slug."""
    override = os.environ.get("HYPERRESEARCH_DUMP_ROOT", "").strip()
    return Path(override) if override else HOST_DUMP_ROOT


def knowledge_dir() -> Path:
    """Directory of accepted ``<slug>.md`` reports."""
    override = os.environ.get("HYPERRESEARCH_KNOWLEDGE_DIR", "").strip()
    return Path(override) if override else HOST_KNOWLEDGE_DIR


def topic_slug(vault_tag: str) -> str:
    """Task slug for a vault tag. The tag itself when it has no 6-hex suffix."""
    match = _SUFFIX.search(vault_tag)
    if match and match.end() == len(vault_tag):
        return vault_tag[: match.start()]
    return vault_tag


def topic_root(vault_tag: str) -> Path:
    """Vault root for one topic: dump/<slug>/."""
    return dump_root() / topic_slug(vault_tag)


def topic_run_dir(vault_tag: str) -> Path:
    """Per-run workspace inside the topic vault."""
    return topic_root(vault_tag) / "output" / "runs" / vault_tag


def topic_notes_dir(vault_tag: str) -> Path:
    """Per-run notes directory inside the topic vault."""
    return topic_root(vault_tag) / "output" / "notes" / vault_tag


def topic_report(vault_tag: str) -> Path:
    """Working report inside the topic vault, before publish."""
    name = f"final_report_{vault_tag}.md"
    return topic_root(vault_tag) / "output" / "reports" / vault_tag / name


def knowledge_report(slug: str) -> Path:
    """Accepted report: one file named for the task."""
    return knowledge_dir() / f"{slug}.md"


def vault_tag_from_argv(argv: Sequence[str] | None = None) -> str | None:
    """First vault tag on the process command line, if any."""
    args = list(sys.argv[1:] if argv is None else argv)
    for index, arg in enumerate(args):
        if arg in _TAG_FLAGS and index + 1 < len(args) and _ARG_TAG.fullmatch(args[index + 1]):
            return args[index + 1]
        if arg.startswith("--tag="):
            candidate = arg.split("=", 1)[1]
            if _ARG_TAG.fullmatch(candidate):
                return candidate
        if _ARG_TAG.fullmatch(arg):
            return arg
    return None
