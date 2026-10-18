"""Lint / health-check CLI commands."""

from __future__ import annotations

import json
import re
from datetime import UTC

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.core.hooks import SCAFFOLD_ONLY_SECTION_HEADERS
from hyperresearch.models.output import success

app = typer.Typer(invoke_without_command=True)

RULES = {
    "missing-title": "Notes without a title",
    "missing-tags": "Notes without any tags",
    "missing-summary": "Notes without a summary",
    "uncurated": "Non-draft notes without tier or content_type classification",
    "workflow": "Hyperresearch artifacts missing (scaffold, loci, interim notes)",
    "scaffold-prompt": "Scaffold notes missing the verbatim user prompt as first section (gospel rule)",
    "wrapper-report": "Final report missing required wrapper contract sections when a harness pinned the canonical query",
    "audit-gate": "Unresolved CRITICAL findings in output/audit_findings.json block synthesis save",
    "provenance": "Source notes with no --suggested-by breadcrumb chain (data-flow chain broken)",
    "locus-coverage": "Loci identified in Layer 2 missing their interim-report notes (depth investigator skipped)",
    "patch-surgery": "Critical critic findings skipped by the patcher (Layer 6 regeneration guard tripped)",
    "instruction-coverage": "Atomic items from prompt-decomposition missing from the final report (draft drifted from user's ask)",
    "citation-style-preservation": "Final report carries no citations matching the declared citation_style (wikilink markers or numbered references stripped)",
    "extract-coverage": "Light-tier runs with fetched sources but no paired extract notes (reading loop skipped or source-analyst not delegated for long sources)",
    "quote-integrity": "Quoted spans in the final report that appear verbatim in no vault note (hallucinated quotes)",
    "numeric-consistency": "Numbers in the final report untraceable to claims or cited note bodies",
    "retracted-citations": "Final report cites a retracted source without marking it as retracted",
    "orphaned-raw-files": "Files in output/raw/ with no matching note (disk leak from old note rm)",
    "singleton-tags": "Tags used by only one note",
    "broken-links": "Wiki-links that don't resolve",
    "orphaned-notes": "Notes with no inbound or outbound links",
    "duplicate-ids": "Multiple notes with the same ID",
    "empty-notes": "Notes with no body content",
    "stale-indexes": "Index pages that need rebuilding",
    "expired-notes": "Notes past their expiry date",
    "stale-reviews": "Notes not reviewed in over 90 days",
}


def _run_dirs_newest_first(vault) -> list:
    """Run workspaces under output/runs/, newest manifest first."""
    runs_dir = vault.research_dir / "runs"
    if not runs_dir.is_dir():
        return []
    dirs = [d for d in runs_dir.iterdir() if d.is_dir() and (d / "run.json").exists()]
    dirs.sort(key=lambda d: (d / "run.json").stat().st_mtime, reverse=True)
    return dirs


def _run_artifact(vault, *relparts: str):
    """Resolve a run-scoped pipeline artifact.

    3.0 layout: output/runs/<vault_tag>/<artifact> (newest run that has it
    wins). Legacy pre-3.0 layout: output/<artifact>. Always returns a Path
    (the legacy flat path when nothing exists anywhere) so `.exists()` checks
    at call sites keep working unchanged.
    """
    for d in _run_dirs_newest_first(vault):
        p = d.joinpath(*relparts)
        if p.exists():
            return p
    return vault.research_dir.joinpath(*relparts)


def _query_files(vault) -> list:
    """Canonical query files: runs/<tag>/query.md (3.0) + legacy query-*.md."""
    files = []
    for d in _run_dirs_newest_first(vault):
        q = d / "query.md"
        if q.exists():
            files.append(q)
    files.extend(sorted((vault.research_dir).glob("query-*.md")))
    return files


def _latest_report(vault):
    """Newest final_report*.md, or (None, None) when no report exists."""
    reports_dir = vault.reports_dir
    if not reports_dir.is_dir():
        return None, None
    candidates = sorted(reports_dir.rglob("final_report*.md"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None, None
    p = candidates[-1]
    try:
        return p, p.read_text(encoding="utf-8-sig")
    except OSError:
        return None, None


_QUOTE_SPAN_RE = re.compile(r"[\"“]([^\"“”]{1,600}?)[\"”]")
_REPORT_NUMBER_RE = re.compile(r"\d[\d,]*\.\d+%?|\d[\d,]{3,}%?|\d[\d,]*%")


def _report_body_only(report_text: str) -> str:
    """Report minus the Sources/References section and citation markers."""
    import re as _re

    body = _re.split(
        r"^##\s+(?:Sources|References)\b", report_text, maxsplit=1, flags=_re.M | _re.I
    )[0]
    return _re.sub(r"\[\d{1,3}(?:\s*,\s*\d{1,3})*\]", "", body)


def _check_quote_integrity(vault, conn, report_path, report_text) -> list[dict]:
    """Every quoted span >= 5 words must exist in some vault note body.

    Uses an FTS phrase query (porter-stemmed on both sides, so inflection
    noise doesn't false-positive) and reports the nearest fuzzy match for
    fast fixing. Hallucinated quotes are error severity — they are the one
    thing a research report can never ship.
    """
    import re as _re

    issues: list[dict] = []
    body = _report_body_only(report_text)
    for m in _QUOTE_SPAN_RE.finditer(body):
        quote = _re.sub(r"\s+", " ", m.group(1)).strip()
        if len(quote.split()) < 5:
            continue
        phrase = quote.replace('"', " ").replace("'", "''")
        try:
            hit = conn.execute(
                "SELECT id FROM notes_fts WHERE notes_fts MATCH ? LIMIT 1",
                (f'body_plain: "{phrase}"',),
            ).fetchone()
        except Exception:
            hit = None
        if hit:
            continue
        issues.append(
            {
                "rule": "quote-integrity",
                "severity": "error",
                "note_id": "<report>",
                "note_path": str(report_path),
                "message": (
                    f'Quoted span not found verbatim in any vault note: "{quote[:120]}"... '
                    "Either the quote is hallucinated/mangled or its source was never fetched. "
                    "Fix the quote or drop the quotation marks."
                ),
            }
        )
    return issues


def _check_numeric_consistency(vault, conn, report_path, report_text) -> list[dict]:
    """Substantive numbers in the report should be traceable to claims or
    cited note bodies. Warning severity — legitimate derived arithmetic
    exists; this flags candidates for the orchestrator to verify, it does
    not block the gate."""
    body = _report_body_only(report_text)
    report_numbers = {n.rstrip(".,") for n in _REPORT_NUMBER_RE.findall(body)}
    if not report_numbers:
        return []

    # Evidence blob: every claim (text, quotes, numbers) + bodies of notes
    # with sources (the citable population).
    parts: list[str] = []
    for row in conn.execute("SELECT claim, quoted_support, numbers FROM claims"):
        parts.extend(filter(None, (row["claim"], row["quoted_support"], row["numbers"])))
    for row in conn.execute(
        "SELECT nc.body_plain FROM note_content nc JOIN notes n ON n.id = nc.note_id "
        "WHERE n.source IS NOT NULL"
    ):
        parts.append(row["body_plain"])
    blob = " ".join(parts).replace(",", "")

    issues: list[dict] = []
    untraced = sorted(n for n in report_numbers if n.replace(",", "") not in blob)
    for number in untraced[:20]:
        issues.append(
            {
                "rule": "numeric-consistency",
                "severity": "warning",
                "note_id": "<report>",
                "note_path": str(report_path),
                "message": (
                    f"Number '{number}' in the final report appears in no claim or cited "
                    "note body. If it is derived arithmetic, fine; otherwise verify it "
                    "against a source or remove it."
                ),
            }
        )
    if len(untraced) > 20:
        issues.append(
            {
                "rule": "numeric-consistency",
                "severity": "warning",
                "note_id": "<report>",
                "note_path": str(report_path),
                "message": f"...and {len(untraced) - 20} more untraceable numbers (showing first 20).",
            }
        )
    return issues


def _check_retracted_citations(vault, conn, report_path, report_text) -> list[dict]:
    """A cited retracted source blocks the gate — unless the citation itself
    acknowledges the retraction (sometimes the retraction IS the story)."""

    from hyperresearch.core.patterns import WIKI_LINK_RE

    retracted = {
        row["id"]: row["title"]
        for row in conn.execute("SELECT id, title FROM notes WHERE is_retracted = 1")
    }
    if not retracted:
        return []

    issues: list[dict] = []
    for m in WIKI_LINK_RE.finditer(report_text):
        target = m.group(1).strip()
        if target not in retracted:
            continue
        window = report_text[max(0, m.start() - 200) : m.end() + 200].lower()
        if "retract" in window:
            continue
        issues.append(
            {
                "rule": "retracted-citations",
                "severity": "error",
                "note_id": target,
                "note_path": str(report_path),
                "message": (
                    f"Final report cites [[{target}]] ('{retracted[target]}') which is "
                    "RETRACTED, without acknowledging the retraction. Drop the citation "
                    "or explicitly mark it (e.g. '(retracted)') where cited."
                ),
            }
        )
    return issues


# keyword -> lint rule for audit-gate guard mapping. Covers the
# natural-language variations in real auditor outputs across modalities.
# Broad on purpose — false matches cause a harmless re-check; a missed
# match is the failure mode guarded against.
_AUDIT_GUARD_KEYWORDS = (
    ("scaffold-prompt", "scaffold-prompt"),
    ("scaffold_prompt", "scaffold-prompt"),
    ("scaffold_extraction_gap", "scaffold-prompt"),
    ("scaffold extraction gap", "scaffold-prompt"),
    ("verbatim prompt", "scaffold-prompt"),
    ("verbatim_prompt", "scaffold-prompt"),
    ("gospel rule", "scaffold-prompt"),
    ("user prompt missing", "scaffold-prompt"),
    ("locus-coverage", "locus-coverage"),
    ("locus coverage", "locus-coverage"),
    ("locus_coverage", "locus-coverage"),
    ("missing interim", "locus-coverage"),
    ("interim note", "locus-coverage"),
    ("depth investigator", "locus-coverage"),
    ("extract-coverage", "extract-coverage"),
    ("extract coverage", "extract-coverage"),
    ("extract_coverage", "extract-coverage"),
    ("extract ratio", "extract-coverage"),
    ("extract notes", "extract-coverage"),
    ("fetch:extract", "extract-coverage"),
    ("analyst skipped", "extract-coverage"),
    ("source-analyst skipped", "extract-coverage"),
    ("no extract", "extract-coverage"),
    ("patch-surgery", "patch-surgery"),
    ("patch surgery", "patch-surgery"),
    ("patch_surgery", "patch-surgery"),
    ("patch log", "patch-surgery"),
    ("critical finding skipped", "patch-surgery"),
    ("regeneration", "patch-surgery"),
    ("instruction-coverage", "instruction-coverage"),
    ("instruction coverage", "instruction-coverage"),
    ("instruction_coverage", "instruction-coverage"),
    ("prompt decomposition", "instruction-coverage"),
    ("prompt-decomposition", "instruction-coverage"),
    ("atomic item", "instruction-coverage"),
    ("atomic items", "instruction-coverage"),
    ("provenance", "provenance"),
    ("suggested-by", "provenance"),
    ("suggested_by", "provenance"),
    ("suggested by", "provenance"),
    ("bouncing reading loop", "provenance"),
    ("bouncing loop", "provenance"),
    ("guided reading loop", "provenance"),
    ("guided loop", "provenance"),
    ("reading loop", "provenance"),
    ("breadcrumb", "provenance"),
    ("data-flow chain", "provenance"),
    ("data flow chain", "provenance"),
    ("data-flow broken", "provenance"),
    ("rabbit-hole", "provenance"),
    ("rabbit hole", "provenance"),
    ("workflow", "workflow"),
    ("missing scaffold", "workflow"),
    ("missing comparison", "workflow"),
    ("missing comparisons", "workflow"),
    ("paired scaffold", "workflow"),
    ("no scaffold note", "workflow"),
    ("no comparison note", "workflow"),
    ("step 7 skipped", "workflow"),
    ("step 8 skipped", "workflow"),
    ("uncurated", "uncurated"),
    ("tier metadata", "uncurated"),
    ("content_type", "uncurated"),
    ("content type", "uncurated"),
    ("tier/content_type", "uncurated"),
    ("tier and content_type", "uncurated"),
    ("classification missing", "uncurated"),
    ("metadata missing", "uncurated"),
    ("missing tier", "uncurated"),
    ("missing summary", "uncurated"),
)


def _audit_gate_load(vault, audit_file, issues: list):
    """Resolve + parse audit_findings.json. Returns the dict or None."""
    import json as _json

    if audit_file:
        audit_path = vault.root / audit_file
    else:
        audit_path = _run_artifact(vault, "audit_findings.json")
    if not audit_path.exists():
        # Missing file = no audit has run yet. Gate stays OPEN so
        # early-stage lint runs don't spam errors.
        return None
    try:
        audit_data = _json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError) as exc:
        issues.append(
            {
                "rule": "audit-gate",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"output/audit_findings.json exists but is malformed "
                    f"({type(exc).__name__}). Delete or fix it, then re-run "
                    f"the adversarial audit."
                ),
            }
        )
        return None
    return audit_data if isinstance(audit_data, dict) else None


def _audit_gate_conformance(
    issues: list, conformance_runs: list, comprehensiveness_runs: list
) -> None:
    # Check (a): a conformance run must exist once any audit has happened.
    # Check (b): no unresolved CRITICALs in the newest conformance run.
    if not conformance_runs:
        if comprehensiveness_runs:
            issues.append(
                {
                    "rule": "audit-gate",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"output/audit_findings.json has "
                        f"{len(comprehensiveness_runs)} comprehensiveness run(s) but ZERO "
                        f"conformance runs. Step 11 mandates BOTH modes. "
                        f"Run the cite-check step (step 14.5) with mode=conformance "
                        f"and wait for it to append its findings to "
                        f"audit_findings.json before saving the synthesis."
                    ),
                }
            )
        # No runs at all = early stage. Gate stays open.
        return
    conformance_runs.sort(key=lambda r: r.get("timestamp", ""))
    latest = conformance_runs[-1]
    unresolved = [c for c in latest.get("criticals") or [] if not c.get("fixed_at")]
    if unresolved:
        issues.append(
            {
                "rule": "audit-gate",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"Most recent conformance audit has "
                    f"{len(unresolved)} unresolved CRITICAL finding(s): "
                    + "; ".join(
                        f"[{c.get('id', '?')}] {c.get('description', '?')[:80]}"
                        for c in unresolved[:5]
                    )
                    + ". Apply the fixes in output/reports/<vault_tag>/final_report_<vault_tag>.md, "
                    + "mark each finding with `fixed_at: <ISO>` in "
                    + "output/audit_findings.json, and re-run the conformance "
                    + "auditor to verify."
                ),
            }
        )
    elif latest.get("status", "unknown") == "failed":
        issues.append(
            {
                "rule": "audit-gate",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    "Most recent conformance audit returned status=failed. "
                    "Investigate the findings and re-run the auditor."
                ),
            }
        )


def _audit_gate_important(issues: list, mode_runs: list, mode_label: str) -> None:
    # Surface IMPORTANT findings as info-severity issues: advisory, no block.
    if not mode_runs:
        return
    mode_runs.sort(key=lambda r: r.get("timestamp", ""))
    unresolved_important = [
        i for i in mode_runs[-1].get("important") or [] if not i.get("fixed_at")
    ]
    if unresolved_important:
        issues.append(
            {
                "rule": "audit-gate",
                "severity": "info",
                "note_id": "<vault>",
                "message": (
                    f"{len(unresolved_important)} unresolved IMPORTANT finding(s) in "
                    f"the latest {mode_label} audit (advisory, does not block save): "
                    + "; ".join(
                        f"[{i.get('id', '?')}] {i.get('description', '?')[:80]}"
                        for i in unresolved_important[:5]
                    )
                    + ". Mark `fixed_at` on each after patching the draft."
                ),
            }
        )


def _match_guard_rule(desc: str):
    for kw, rule_name in _AUDIT_GUARD_KEYWORDS:
        if kw in desc:
            return rule_name
    return None


def _emit_guard(issues: list, rules_to_run: list, guards: list, critical: dict, matched) -> None:
    if not matched:
        # CRITICAL marked fixed_at but no known lint rule maps to its
        # description. Trust-only — surface a warning, we cannot verify it.
        issues.append(
            {
                "rule": "audit-gate",
                "severity": "warning",
                "note_id": "<vault>",
                "message": (
                    f"CRITICAL [{critical.get('id', '?')}] was marked `fixed_at` but "
                    f"its description doesn't map to any known lint rule: "
                    f"'{(critical.get('description', '') or '')[:100]}'. The fix is "
                    f"agent-self-reported and not machine-verified. Review the "
                    f"draft manually to confirm the issue was actually addressed."
                ),
            }
        )
        return
    guards.append(
        {
            "critical_id": critical.get("id", "?"),
            "rule": matched,
            "description": critical.get("description", "")[:120],
        }
    )
    # Ensure the guard rule runs so we can check its issues in post-processing.
    if matched not in rules_to_run:
        rules_to_run.append(matched)


def _audit_gate_guards(issues: list, rules_to_run: list, guards: list, mode_runs: list) -> None:
    # For each fixed CRITICAL, queue its implied lint rule for verification
    # (self-certification detection). Unresolved criticals already emitted.
    if not mode_runs:
        return
    latest_run = sorted(mode_runs, key=lambda r: r.get("timestamp", ""))[-1]
    for c in latest_run.get("criticals") or []:
        if not c.get("fixed_at"):
            continue
        desc = (str(c.get("description", "")) + " " + str(c.get("id", ""))).lower()
        _emit_guard(issues, rules_to_run, guards, c, _match_guard_rule(desc))


def _lint_audit_gate(vault, conn, issues: list, run) -> None:
    # Block synthesis save unless BOTH a conformance audit run exists AND
    # every CRITICAL finding in the newest one carries fixed_at.
    audit_data = _audit_gate_load(vault, run.audit_file, issues)
    if audit_data is None:
        return
    runs = audit_data.get("runs", [])
    conformance_runs = [r for r in runs if r.get("mode") == "conformance"]
    comprehensiveness_runs = [r for r in runs if r.get("mode") == "comprehensiveness"]
    _audit_gate_conformance(issues, conformance_runs, comprehensiveness_runs)
    _audit_gate_important(issues, conformance_runs, "conformance")
    _audit_gate_important(issues, comprehensiveness_runs, "comprehensiveness")
    _audit_gate_guards(issues, run.rules, run.guards, conformance_runs)
    _audit_gate_guards(issues, run.rules, run.guards, comprehensiveness_runs)


def _read_query_prompt(query_files: list):
    """Read the newest query file. Returns the prompt text or None."""
    # Use the first (newest) for 3.0 runs, last for pure-legacy vaults.
    picked = [query_files[0]] if query_files[0].name == "query.md" else query_files
    try:
        raw = picked[-1].read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except OSError:
        return None
    # Strip YAML frontmatter if present
    if raw.startswith("---"):
        end = raw.find("\n---\n", 3)
        if end != -1:
            raw = raw[end + 5 :]
    return raw.rstrip("\n")


def _canonical_prompt_text(vault):
    """Canonical user prompt, or None when no artifact exists."""
    # Check for query files first (runs/<tag>/query.md, then legacy
    # output/query-*.md), fall back to legacy prompt.txt
    query_files = _query_files(vault)
    canonical = _read_query_prompt(query_files) if query_files else None
    if canonical is None and (vault.research_dir / "prompt.txt").exists():
        try:
            canonical = (
                (vault.research_dir / "prompt.txt")
                .read_text(encoding="utf-8-sig")
                .replace("\r\n", "\n")
                .rstrip("\n")
            )
        except OSError:
            canonical = None
    return canonical


def _extract_prompt_text(body_lines: list[str], header_line_idx: int) -> str:
    prompt_lines: list[str] = []
    for line in body_lines[header_line_idx + 1 :]:
        stripped = line.rstrip("\r\n")
        if stripped.lstrip().startswith("##"):
            break
        if stripped.lstrip().startswith(">"):
            raw = stripped.lstrip()[1:]
            if raw.startswith(" "):
                raw = raw[1:]
            prompt_lines.append(raw)
        else:
            prompt_lines.append(stripped)
    while prompt_lines and not prompt_lines[0]:
        prompt_lines.pop(0)
    while prompt_lines and not prompt_lines[-1]:
        prompt_lines.pop()
    return "\n".join(prompt_lines).replace("\r\n", "\n")


def _find_prompt_header(body_lines: list, header_re):
    # Look for the header within the first 20 non-blank lines
    seen_non_blank = 0
    for idx, line in enumerate(body_lines):
        if line.strip():
            seen_non_blank += 1
        if header_re.match(line):
            return idx
        if seen_non_blank >= 20:
            break
    return None


def _check_scaffold_row(row, header_re, canonical_prompt, issues: list) -> None:
    body_lines = [str(line) for line in (row["body"] or "").splitlines()]
    header_line_idx = _find_prompt_header(body_lines, header_re)
    if header_line_idx is None:
        issues.append(
            {
                "rule": "scaffold-prompt",
                "severity": "error",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": (
                    "Scaffold is missing the verbatim user prompt as its first section. "
                    "Every scaffold MUST open with a `## User Prompt (VERBATIM — gospel)` "
                    "header followed by the user's original question as a blockquote. "
                    "This is the gospel rule — the dispatcher re-reads the prompt from "
                    "this section at every downstream step."
                ),
            }
        )
        return
    extracted_prompt = _extract_prompt_text(body_lines, header_line_idx)
    # When a canonical prompt artifact exists, require exact equality
    # (modulo line-ending normalization only). This turns the scaffold
    # rule from "has something prompt-like" into a real contract check.
    if canonical_prompt is not None:
        if extracted_prompt != canonical_prompt:
            issues.append(
                {
                    "rule": "scaffold-prompt",
                    "severity": "error",
                    "note_id": row["id"],
                    "note_path": row["path"],
                    "message": (
                        "Scaffold prompt does not exactly match output/prompt.txt. "
                        "The verbatim prompt is a hard contract when a harness pins it — "
                        "re-copy it character-for-character under the "
                        "`## User Prompt (VERBATIM — gospel)` header."
                    ),
                }
            )
        return
    # Fallback for vaults without a canonical-prompt artifact with no canonical prompt artifact:
    # require non-trivial content after the header so the rule still
    # protects against empty placeholder scaffolds.
    quote_chars = len(extracted_prompt)
    if quote_chars < 50:
        issues.append(
            {
                "rule": "scaffold-prompt",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": (
                    f"Scaffold has the verbatim-prompt header but the content after it "
                    f"is empty or too short ({quote_chars} chars). Paste the user's "
                    f"full prompt as a blockquote under the header."
                ),
            }
        )


def _lint_scaffold_prompt(vault, conn, issues: list, run) -> None:
    # Enforce the gospel rule: every scaffold-tagged note must open with
    # the user's verbatim prompt as its first section. This is the single
    # machine-checkable invariant that protects the dispatcher's
    # "user prompt is gospel" commitment. Without this check, scaffolds
    # can drift — an agent writes a `## Thesis` opening, never pastes the
    # verbatim prompt, and every downstream step that re-reads the
    # scaffold (audit, draft, comparisons) loses its anchor.
    import re as _re

    header_re = _re.compile(
        r"^\s*##\s+User\s+Prompt\s*\(\s*VERBATIM.*gospel\s*\)",
        _re.IGNORECASE,
    )
    canonical_prompt = _canonical_prompt_text(vault)
    for row in conn.execute("""
        SELECT n.id, n.path, nc.body
        FROM notes n
        JOIN note_content nc ON n.id = nc.note_id
        WHERE n.id IN (SELECT note_id FROM tags WHERE tag = 'scaffold')
    """):
        _check_scaffold_row(row, header_re, canonical_prompt, issues)


def _load_wrapper_contract(vault, issues: list):
    contract_path = vault.research_dir / "wrapper_contract.json"
    if not contract_path.exists():
        return None
    try:
        return json.loads(contract_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(
            {
                "rule": "wrapper-report",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"wrapper_contract.json exists but is unreadable: "
                    f"{type(exc).__name__}: {exc}. Fix the JSON or remove "
                    f"the file."
                ),
            }
        )
        return None


def _find_final_report(vault):
    # Reports are now named final_report_<vault_tag>.md. Glob to find
    # any matching report; fall back to the legacy bare name for
    # back-compat with pre-0.8.5 runs.
    reports_dir = vault.reports_dir
    report_candidates = (
        sorted(
            reports_dir.rglob("final_report*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if reports_dir.exists()
        else []
    )
    return report_candidates[0] if report_candidates else (reports_dir / "final_report.md")


def _read_report_body(report_path, issues: list) -> str:
    try:
        return report_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except OSError as exc:
        issues.append(
            {
                "rule": "wrapper-report",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"Could not read final report at {report_path}: "
                    f"{type(exc).__name__}."
                ),
            }
        )
        return ""


def _check_required_headers(report_body: str, wrapper_contract, issues: list) -> None:
    # Wrapper-declared required terminal sections (optional).
    required_headers: list[str] = []
    if wrapper_contract is not None:
        raw = wrapper_contract.get("required_terminal_sections", [])
        if isinstance(raw, list):
            required_headers = [str(h) for h in raw if isinstance(h, str)]
    missing_headers = [h for h in required_headers if h not in report_body]
    if missing_headers:
        issues.append(
            {
                "rule": "wrapper-report",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    "wrapper_contract.json declares required_terminal_sections "
                    "that are missing from the final report. Missing: "
                    f"{', '.join(missing_headers)}."
                ),
            }
        )


def _check_scaffold_leak(report_body: str, wrapper_contract, issues: list) -> None:
    # Scaffold-leak hygiene: ALWAYS enforced. Base list comes from
    # the canonical SCAFFOLD_ONLY_SECTION_HEADERS constant in
    # hooks.py (shared with the three agent prompts). Wrapper can
    # declare additional forbidden body sections on top.
    forbidden_headers = list(SCAFFOLD_ONLY_SECTION_HEADERS)
    if wrapper_contract is not None:
        extra = wrapper_contract.get("forbidden_body_sections", [])
        if isinstance(extra, list):
            for h in extra:
                if isinstance(h, str) and h not in forbidden_headers:
                    forbidden_headers.append(h)
    leaked = [h for h in forbidden_headers if h in report_body]
    if leaked:
        issues.append(
            {
                "rule": "wrapper-report",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    "Final report is leaking scaffold-only sections into "
                    "the deliverable. Remove: "
                    f"{', '.join(leaked)}."
                ),
            }
        )


def _check_report_sections(vault, report_path, wrapper_contract, issues: list) -> None:
    report_body = _read_report_body(report_path, issues)
    _check_required_headers(report_body, wrapper_contract, issues)
    _check_scaffold_leak(report_body, wrapper_contract, issues)


def _lint_wrapper_report(vault, conn, issues: list, run) -> None:
    # The rule activates when either signals a wrapped harness context:
    #   - output/prompt.txt or output/query-*.md exists (canonical query)
    #   - output/wrapper_contract.json exists (harness declared packaging)
    #
    # Required terminal sections are READ from wrapper_contract.json, not
    # hardcoded. This keeps the lint mechanism-focused — any wrapper can
    # declare its own packaging contract and the rule will enforce it
    # verbatim. No wrapper declared => skip the terminal-section check
    # but still enforce scaffold-leak hygiene (always wrong regardless
    # of wrapper).
    wrapper_contract = _load_wrapper_contract(vault, issues)
    prompt_path = vault.research_dir / "prompt.txt"
    if not (prompt_path.exists() or _query_files(vault) or wrapper_contract is not None):
        return
    report_path = _find_final_report(vault)
    if not report_path.exists():
        issues.append(
            {
                "rule": "wrapper-report",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    "Wrapped research context detected (prompt.txt, "
                    "query-*.md, or wrapper_contract.json present) but "
                    "no `output/reports/*/final_report*.md` file is present. "
                    "The final report must exist before export."
                ),
            }
        )
        return
    _check_report_sections(vault, report_path, wrapper_contract, issues)


def _collect_breadcrumbs(source_rows, breadcrumb_re) -> dict:
    source_breadcrumbs: dict[str, list[str]] = {}
    for r in source_rows:
        targets = breadcrumb_re.findall(r["body"] or "")
        # Keep only the wiki-link name before any `|display` pipe.
        source_breadcrumbs[r["id"]] = [t.split("|", 1)[0].strip() for t in targets]
    return source_breadcrumbs


def _check_seed_exists(issues: list, seeds: list, source_count: int) -> None:
    # Condition 1: at least one seed.
    if seeds:
        return
    issues.append(
        {
            "rule": "provenance",
            "severity": "error",
            "note_id": "<vault>",
            "message": (
                f"Provenance graph has no seed: every one of {source_count} source notes "
                f"carries a `*Suggested by [[...]]` breadcrumb, which is impossible for a real "
                f"research session. The guided reading loop must start from at least one seed "
                f"fetch with no suggester."
            ),
        }
    )


def _collect_dangling(source_breadcrumbs: dict, non_seeds: list, all_note_ids: set) -> list:
    dangling: list[tuple[str, str]] = []
    for nid in non_seeds:
        for target in source_breadcrumbs[nid]:
            if target not in all_note_ids:
                dangling.append((nid, target))
    return dangling


def _report_dangling(issues: list, dangling: list) -> None:
    for src_id, target in dangling[:10]:  # cap output
        issues.append(
            {
                "rule": "provenance",
                "severity": "error",
                "note_id": src_id,
                "message": (
                    f"Breadcrumb `[[{target}]]` points at a note id that does not exist in the "
                    f"vault. Either the target was deleted, or the breadcrumb was hand-written "
                    f"without a real source. Re-fetch with `--suggested-by <real-note-id>`."
                ),
            }
        )


def _reachable_from_seeds(seeds: list, source_breadcrumbs: dict) -> set:
    # BFS from seeds to verify connectivity.
    reachable = set(seeds)
    frontier = list(seeds)
    # Build reverse map: suggester -> notes it sourced
    suggester_to_sourced: dict[str, list[str]] = {}
    for nid, crumbs in source_breadcrumbs.items():
        for t in crumbs:
            suggester_to_sourced.setdefault(t, []).append(nid)
    while frontier:
        current = frontier.pop()
        for child in suggester_to_sourced.get(current, []):
            if child not in reachable:
                reachable.add(child)
                frontier.append(child)
    return reachable


def _check_reachability(issues: list, seeds: list, source_breadcrumbs: dict, non_seeds: list) -> None:
    reachable = _reachable_from_seeds(seeds, source_breadcrumbs)
    unreachable = [nid for nid in non_seeds if nid not in reachable]
    if unreachable:
        issues.append(
            {
                "rule": "provenance",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"{len(unreachable)} source note(s) have breadcrumbs but are not reachable "
                    f"from any seed through the provenance graph — the chain is disconnected. "
                    f"Disconnected islands usually mean an agent fabricated breadcrumbs "
                    f"retroactively without following the guided reading loop. First few: "
                    f"{', '.join(unreachable[:5])}"
                ),
            }
        )


def _check_breadcrumb_coverage(vault, issues: list, source_rows: list, non_seeds: list) -> None:
    # Coverage / bouncing-loop heuristic: DOES NOT APPLY to hyperresearch runs.
    # (Ensemble uses an analyst-driven loop where 30-50% of sources carry
    # breadcrumbs; hyperresearch fetches mostly planned seeds + locus-driven
    # depth fetches.) Skip the ratio checks when loci.json exists; the
    # structural invariants above still apply.
    if _run_artifact(vault, "loci.json").exists():
        return
    if len(source_rows) > 5 and len(non_seeds) == 0:
        issues.append(
            {
                "rule": "provenance",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"Vault has {len(source_rows)} fetched source notes but ZERO "
                    f"`*Suggested by [[...]]` breadcrumbs. The bouncing reading loop never "
                    f"fired — every fetch was a flat batch with no link back to the source "
                    f"that proposed it. Use `$HPR fetch ... --suggested-by <source-note-id> "
                    f'--suggested-by-reason "<why>"` for every follow-up fetch.'
                ),
            }
        )
    elif len(non_seeds) / max(len(source_rows), 1) < 0.3 and len(source_rows) > 10:
        ratio = len(non_seeds) / max(len(source_rows), 1)
        issues.append(
            {
                "rule": "provenance",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"Only {len(non_seeds)}/{len(source_rows)} source notes ({ratio:.0%}) "
                    f"have breadcrumbs — the guided reading loop did not fire. The initial batch "
                    f"fetch is not the whole corpus; after fetching seeds you MUST spawn analysts "
                    f"to propose next targets, then fetch those with `--suggested-by`. Target: "
                    f"at least 30% of sources should come from analyst recommendations."
                ),
            }
        )
    elif len(non_seeds) / max(len(source_rows), 1) < 0.5 and len(source_rows) > 10:
        ratio = len(non_seeds) / max(len(source_rows), 1)
        issues.append(
            {
                "rule": "provenance",
                "severity": "warning",
                "note_id": "<vault>",
                "message": (
                    f"Only {len(non_seeds)}/{len(source_rows)} source notes ({ratio:.0%}) "
                    f"have breadcrumbs. The bouncing reading loop is under-firing — most "
                    f"fetches look like flat seeds rather than analyst-driven discoveries."
                ),
            }
        )


def _check_provenance_graph(vault, conn, issues: list, source_rows: list, breadcrumb_re) -> None:
    all_note_ids = {r["id"] for r in conn.execute("SELECT id FROM notes")}
    source_breadcrumbs = _collect_breadcrumbs(source_rows, breadcrumb_re)
    seeds = [nid for nid, crumbs in source_breadcrumbs.items() if not crumbs]
    non_seeds = [nid for nid, crumbs in source_breadcrumbs.items() if crumbs]
    # Condition 1: at least one seed.
    _check_seed_exists(issues, seeds, len(source_rows))
    # Condition 2 + 3: rooted at seeds, no dangling targets.
    if non_seeds:
        _report_dangling(issues, _collect_dangling(source_breadcrumbs, non_seeds, all_note_ids))
        _check_reachability(issues, seeds, source_breadcrumbs, non_seeds)
    _check_breadcrumb_coverage(vault, issues, source_rows, non_seeds)


def _lint_provenance(vault, conn, issues: list, run) -> None:
    # Verify the `--suggested-by` data-flow chain forms a rooted tree
    # (or forest) across all fetched source notes. Previous version used
    # `breadcrumb_count < max(2, source_count // 5)` which was easy to game
    # by backfilling N//5 unrelated breadcrumbs. The rooted-tree check
    # cannot be satisfied without an actual chain.
    import re as _re

    breadcrumb_re = _re.compile(r"\*Suggested by \[\[([^\]]+)\]\]")
    source_rows = list(
        conn.execute(
            "SELECT n.id, n.path, nc.body "
            "FROM notes n "
            "JOIN note_content nc ON n.id = nc.note_id "
            "WHERE n.source IS NOT NULL "
            "AND n.id NOT LIKE '\\_%' ESCAPE '\\' "
            "AND n.type NOT IN ('index','raw','moc')"
        )
    )
    if len(source_rows) <= 5:
        # Small corpora: bouncing loop may not have fired by design.
        # Skip the structural check; fall back to presence check only.
        return
    _check_provenance_graph(vault, conn, issues, source_rows, breadcrumb_re)


def _load_loci_list(vault, issues: list) -> list | None:
    """Parse output/loci.json. Returns the loci list, [] on error, None when absent."""
    loci_path = _run_artifact(vault, "loci.json")
    if not loci_path.exists():
        return None
    try:
        loci_data = json.loads(loci_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        issues.append(
            {
                "rule": "locus-coverage",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    "output/loci.json exists but is not valid JSON. "
                    "Layer 2 output corrupted — re-run loci analysis."
                ),
            }
        )
        return []
    return loci_data.get("loci", []) if isinstance(loci_data, dict) else loci_data


def _count_interim_notes(conn, tag: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as c FROM notes n "
        "JOIN tags t ON t.note_id = n.id "
        "WHERE t.tag = ? AND n.type = 'interim'",
        (tag,),
    ).fetchone()
    return row["c"] if row else 0


def _scan_locus_interims(conn, loci_list: list) -> tuple:
    """Returns (missing_loci, duplicate_loci)."""
    missing_loci: list[str] = []
    duplicate_loci: list[tuple[str, int]] = []
    for locus in loci_list:
        if not isinstance(locus, dict):
            continue
        name = locus.get("name")
        if not name:
            continue
        interim_count = _count_interim_notes(conn, f"locus-{name}")
        if interim_count == 0:
            missing_loci.append(name)
        elif interim_count > 1:
            duplicate_loci.append((name, interim_count))
    return missing_loci, duplicate_loci


def _report_missing_loci(issues: list, missing_loci: list, loci_count: int) -> None:
    if not missing_loci:
        return
    severity = "error" if len(missing_loci) >= 2 else "warning"
    issues.append(
        {
            "rule": "locus-coverage",
            "severity": severity,
            "note_id": "<vault>",
            "message": (
                f"{len(missing_loci)} of {loci_count} loci have no interim note: "
                f"{', '.join(missing_loci[:6])}{'...' if len(missing_loci) > 6 else ''}. "
                "The depth investigator either failed or was skipped. "
                "Layer 3 must produce one `interim-<locus>.md` note per locus "
                "with `type: interim` and `tag: locus-<name>`."
            ),
        }
    )


def _report_duplicate_loci(issues: list, duplicate_loci: list) -> None:
    # Duplicate interim notes on the same locus — a past failure
    # mode where one locus accumulated 3 interim notes. Inflates
    # source count and confuses Layer 5 critics. Warn when any
    # locus has >1 interim.
    if not duplicate_loci:
        return
    summary = ", ".join(f"{n} ({c})" for n, c in duplicate_loci[:6])
    issues.append(
        {
            "rule": "locus-coverage",
            "severity": "warning",
            "note_id": "<vault>",
            "message": (
                f"{len(duplicate_loci)} locus/loci have duplicate interim notes: "
                f"{summary}. Depth investigators must check for an existing "
                "interim note on their locus before calling `note new`; if one "
                "exists, use `note update` or report back to the orchestrator. "
                "Delete the weaker copies manually."
            ),
        }
    )


def _lint_locus_coverage(vault, conn, issues: list, run) -> None:
    # Hyperresearch step 2 produces `output/loci.json` (the deduped loci list
    # the orchestrator commits to). Layer 3 must produce one interim note
    # per locus, tagged `locus-<locus-name>` with `type: interim`. This
    # rule catches depth investigators that failed or were skipped.
    loci_list = _load_loci_list(vault, issues)
    if loci_list is None:
        return
    missing_loci, duplicate_loci = _scan_locus_interims(conn, loci_list)
    _report_missing_loci(issues, missing_loci, len(loci_list))
    _report_duplicate_loci(issues, duplicate_loci)


def _scalar_count(conn, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return row["c"] if row else 0


def _extract_coverage_note(stub_count: int, unlinked_real: int, extract_min_words: int) -> str:
    notes_parts = []
    if stub_count:
        notes_parts.append(f"{stub_count} stub notes under {extract_min_words} words, not counted")
    if unlinked_real:
        notes_parts.append(
            f"{unlinked_real} unlinked real extracts missing a valid parent source-id, not counted"
        )
    return f" (plus {'; '.join(notes_parts)})" if notes_parts else ""


def _check_extract_ratio(vault, issues: list, source_count: int, extract_count: int, stub_count: int, unlinked_real: int, extract_min_words: int) -> None:
    # Require 1/3 coverage (error floor at 1/4). Even a 2-source
    # session needs at least 1 extract — the analyst is mandatory
    # on single-pass runs, not optional.
    if source_count < 1:
        return
    divisor = vault.config.lint.extract_coverage_divisor
    required_extracts = max(1, source_count // divisor)
    error_floor = max(1, source_count // (divisor + 1))
    if extract_count >= required_extracts:
        return
    ratio = extract_count / source_count if source_count else 0
    stub_note = _extract_coverage_note(stub_count, unlinked_real, extract_min_words)
    issues.append(
        {
            "rule": "extract-coverage",
            "severity": "error" if extract_count < error_floor else "warning",
            "note_id": "<vault>",
            "message": (
                f"Vault has {source_count} fetched source notes but only {extract_count} "
                f"real source-linked extract notes{stub_note} "
                f"({ratio:.0%} coverage, need ≥{required_extracts}). "
                f"The analyst was skipped on most sources or the source->extract chain "
                f"of custody is broken. Spawn an analyst subagent on the unanalyzed "
                f"sources during curation. Target: at least 1 extract "
                f"(≥{extract_min_words} words, with `parent=<source-note-id>`) per 3 "
                f"sources (floor of 1 for any corpus size). Minting stub notes to "
                f"pass this gate is lint-gaming and will not satisfy."
            ),
        }
    )


def _lint_extract_coverage(vault, conn, issues: list, run) -> None:
    # Single-pass /research runs use the "bouncing reading loop": fetch a
    # seed, analyst reads it and proposes next URLs, main agent fetches
    # those, loop. Each fetched source should have a paired extract note
    # (tagged `extract`) with ≥150 words of real content. This rule
    # enforces that discipline — it catches flat-batch fetchers who never
    # spawned an analyst, AND it catches stub-padding attacks where the
    # agent mints hollow extract notes to pass numerical coverage.
    #
    # Hyperresearch runs use a different artifact shape (interim notes per
    # locus, checked by `locus-coverage`). Skip this rule when
    # `output/loci.json` exists — that signals a hyperresearch run.
    if _run_artifact(vault, "loci.json").exists():
        return
    extract_min_words = vault.config.lint.extract_min_words
    source_count = _scalar_count(
        conn,
        "SELECT COUNT(*) as c FROM notes n "
        "WHERE n.source IS NOT NULL "
        "AND n.id NOT LIKE '\\_%' ESCAPE '\\' "
        "AND n.type NOT IN ('index','raw','moc') "
        "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'extract') "
        "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'scaffold') "
        "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'comparison') "
        "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'dud')",
    )
    # REAL extracts: tagged `extract`, body ≥150 words, with parent
    # pointing at a real source note (chain of custody). Stubs and
    # unlinked real-looking extracts don't satisfy.
    extract_count = _scalar_count(
        conn,
        "SELECT COUNT(DISTINCT n.id) as c FROM notes n "
        "JOIN tags t ON t.note_id = n.id "
        "WHERE t.tag = 'extract' "
        "AND n.word_count >= ? "
        "AND n.parent IS NOT NULL AND n.parent != '' "
        "AND n.parent IN (SELECT id FROM notes WHERE source IS NOT NULL) "
        "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'dud')",
        (extract_min_words,),
    )
    # Count stubs separately so the lint message stays honest — a
    # vault with 13 real + 45 stub extracts should show that, not
    # silently collapse to "13 extracts".
    stub_count = _scalar_count(
        conn,
        "SELECT COUNT(DISTINCT n.id) as c FROM notes n "
        "JOIN tags t ON t.note_id = n.id "
        "WHERE t.tag = 'extract' AND n.word_count < ? "
        "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'dud')",
        (extract_min_words,),
    )
    # Real extracts with no valid parent — broken chain of custody.
    unlinked_real = _scalar_count(
        conn,
        "SELECT COUNT(DISTINCT n.id) as c FROM notes n "
        "JOIN tags t ON t.note_id = n.id "
        "WHERE t.tag = 'extract' "
        "AND n.word_count >= ? "
        "AND (n.parent IS NULL OR n.parent = '' "
        "     OR n.parent NOT IN (SELECT id FROM notes WHERE source IS NOT NULL)) "
        "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'dud')",
        (extract_min_words,),
    )
    _check_extract_ratio(
        vault, issues, source_count, extract_count, stub_count, unlinked_real, extract_min_words
    )


def _load_patch_log(vault, issues: list):
    """Parse output/patch-log.json. Returns the dict, {} on error, None when absent."""
    patch_log_path = _run_artifact(vault, "patch-log.json")
    if not patch_log_path.exists():
        return None
    try:
        return json.loads(patch_log_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        issues.append(
            {
                "rule": "patch-surgery",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    "output/patch-log.json exists but is not valid JSON. "
                    "Layer 6 output corrupted."
                ),
            }
        )
        return {}


def _check_skipped_criticals(log: dict, issues: list) -> list:
    skipped = log.get("skipped", []) if isinstance(log, dict) else []
    critical_skipped = [
        e for e in skipped if isinstance(e, dict) and e.get("severity") == "critical"
    ]
    if critical_skipped:
        names = ", ".join(
            f"#{e.get('finding_id', '?')} ({e.get('critic', '?')})" for e in critical_skipped[:5]
        )
        issues.append(
            {
                "rule": "patch-surgery",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"{len(critical_skipped)} critical finding(s) skipped by patcher: "
                    f"{names}. The draft shipped with known-critical issues unresolved. "
                    "Inspect output/patch-log.json and either hand-craft Edits or "
                    "re-spawn the critics with more specific recommendations."
                ),
            }
        )
    return skipped


def _count_critic_findings(vault) -> int:
    critic_totals = 0
    for name in ("dialectic", "depth", "width"):
        cf = _run_artifact(vault, f"critic-findings-{name}.json")
        if not cf.exists():
            continue
        try:
            critic_totals += len(json.loads(cf.read_text(encoding="utf-8")).get("findings", []))
        except (json.JSONDecodeError, OSError):
            pass
    return critic_totals


def _check_empty_patch_log(vault, log: dict, skipped: list, issues: list) -> None:
    # "Empty log" detector — distinguishes "patcher ran, log lost" from
    # "patcher ran, applied nothing legitimately".
    #
    # If: (a) there are critic findings files with >0 findings AND
    #     (b) the final report exists AND
    #     (c) the patch log's applied+skipped+conflicts total is 0
    # then the patcher's log was lost in transit (e.g., the log-stub
    # file wasn't pre-created, so the Edit-only patcher couldn't
    # populate it and inlined the log in its Task result). The real
    # patches DID get applied to the draft, but the audit trail is
    # gone — we can't verify what the patcher did.
    applied = log.get("applied", []) if isinstance(log, dict) else []
    conflicts = log.get("conflicts", []) if isinstance(log, dict) else []
    total_logged = len(applied) + len(skipped) + len(conflicts)
    critic_totals = _count_critic_findings(vault)
    reports_dir = vault.reports_dir
    final_report_exists = bool(
        sorted(reports_dir.rglob("final_report*.md")) if reports_dir.exists() else []
    )
    if total_logged == 0 and critic_totals > 0 and final_report_exists:
        issues.append(
            {
                "rule": "patch-surgery",
                "severity": "warning",
                "note_id": "<vault>",
                "message": (
                    f"Patch log is empty (applied=0, skipped=0, conflicts=0) "
                    f"but critics returned {critic_totals} findings and the "
                    "final report exists. The patcher's log was almost "
                    "certainly lost in transit — Layer 6 orchestrator "
                    "didn't pre-create `output/patch-log.json` as an "
                    "empty stub, so the tool-locked patcher (`[Read, Edit]` "
                    "only) couldn't populate it and inlined the log in its "
                    "Task result instead. The draft WAS patched — you can "
                    "verify via `git diff` on the L4 draft snapshot — but "
                    "the audit trail is gone. Fix: orchestrator must "
                    '`echo \'{"applied":[], "skipped":[], "conflicts":[]}\' '
                    "> output/patch-log.json` before spawning the patcher."
                ),
            }
        )


def _lint_patch_surgery(vault, conn, issues: list, run) -> None:
    # Layer 6 writes output/patch-log.json. The log records applied,
    # skipped, and conflicted findings. Skipped `critical` findings are
    # blockers — the draft shipped with a critical critique unresolved.
    # This rule surfaces that.
    log = _load_patch_log(vault, issues)
    if log is None:
        return
    skipped = _check_skipped_criticals(log, issues)
    _check_empty_patch_log(vault, log, skipped, issues)


def _load_decomposition(vault, issues: list):
    decomp_path = _run_artifact(vault, "prompt-decomposition.json")
    if not decomp_path.exists():
        return None
    try:
        decomp = json.loads(decomp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        issues.append(
            {
                "rule": "instruction-coverage",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"output/prompt-decomposition.json exists but is "
                    f"not valid JSON: {exc}. Layer 0.5 output corrupted."
                ),
            }
        )
        return None
    return decomp if isinstance(decomp, dict) else None


def _check_missing_entities(decomp: dict, report_lower: str, issues: list) -> None:
    missing_entities: list[str] = []
    for ent in decomp.get("entities", []) or []:
        if not isinstance(ent, dict):
            continue
        name = ent.get("name") or ""
        if name and name.lower() not in report_lower:
            missing_entities.append(name)
    if not missing_entities:
        return
    severity = "error" if len(missing_entities) >= 3 else "warning"
    preview = ", ".join(missing_entities[:8])
    if len(missing_entities) > 8:
        preview += f", ... (+{len(missing_entities) - 8} more)"
    issues.append(
        {
            "rule": "instruction-coverage",
            "severity": severity,
            "note_id": "<vault>",
            "message": (
                f"{len(missing_entities)} atomic entity/entities "
                f"from prompt-decomposition.json are missing from "
                f"the final report: {preview}. The draft drifted "
                "from the user's explicit ask. Re-spawn the "
                "instruction-critic with the missing items "
                "flagged, or hand-craft Edits to restore them."
            ),
        }
    )


def _check_missing_formats(decomp: dict, report_lower: str, issues: list) -> None:
    # Required formats are a more structural check — we can't
    # reliably grep for "is this a mind map" — but if the format
    # name is literally missing from the prose, that's a signal.
    missing_formats: list[str] = []
    for fmt in decomp.get("required_formats", []) or []:
        if not isinstance(fmt, str):
            continue
        # Pull the content-word from the format spec (e.g., "mind
        # map of causal structure" → "mind map")
        head = fmt.split(" of ")[0].strip().lower()
        if head and head not in report_lower:
            missing_formats.append(fmt)
    if missing_formats:
        issues.append(
            {
                "rule": "instruction-coverage",
                "severity": "warning",
                "note_id": "<vault>",
                "message": (
                    f"Required format(s) from prompt-decomposition not "
                    f"visibly present in draft: {', '.join(missing_formats[:5])}. "
                    "This may be a false positive if the format is "
                    "rendered without the spec word in the prose — "
                    "review manually."
                ),
            }
        )


def _lint_instruction_coverage(vault, conn, issues: list, run) -> None:
    # Layer 0.5 produces `output/prompt-decomposition.json` — a structured
    # breakdown of the atomic items the user's prompt named (sub-questions,
    # entities, required formats, etc.). The final_report.md is expected to
    # cover every atomic item. This rule does a lightweight text-presence
    # check: for each named entity or sub-question in the decomposition,
    # verify the final report mentions it.
    #
    # This is a shallow check — surface presence, not structural mirroring.
    # The instruction-critic agent (Layer 5) does the deeper structural
    # audit. This lint rule is the final post-patch gate that catches
    # items the critic flagged but the patcher couldn't apply.
    final_report = _find_final_report(vault)
    if not final_report.exists():
        return
    decomp = _load_decomposition(vault, issues)
    if decomp is None:
        return
    try:
        report_text = final_report.read_text(encoding="utf-8")
    except OSError:
        report_text = ""
    report_lower = report_text.lower()
    _check_missing_entities(decomp, report_lower, issues)
    _check_missing_formats(decomp, report_lower, issues)


def _read_style_setting(path, encoding: str):
    """Read citation_style from a JSON file. Returns the str or None."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding=encoding))
    except (OSError, json.JSONDecodeError):
        # Unreadable here is reported by its owning rule; don't double-report.
        return None
    if isinstance(data, dict) and isinstance(data.get("citation_style"), str):
        return data["citation_style"]
    return None


def _declared_citation_style(vault):
    style = _read_style_setting(_run_artifact(vault, "prompt-decomposition.json"), "utf-8")
    # Wrapper contract overrides the decomposition's citation_style
    # (read at lint time, so a mid-pipeline wrapper change wins naturally).
    contract_style = _read_style_setting(vault.research_dir / "wrapper_contract.json", "utf-8-sig")
    if contract_style is not None:
        style = contract_style
    return style


def _check_wikilink_citations(conn, report_path, report_text: str, issues: list) -> None:
    import re as _re

    all_note_ids = {r["id"] for r in conn.execute("SELECT id FROM notes")}
    targets = [t.split("|", 1)[0].strip() for t in _re.findall(r"\[\[([^\]]+)\]\]", report_text)]
    resolved = [t for t in targets if t in all_note_ids]
    if resolved:
        return
    detail = (
        f"it contains {len(targets)} wikilink(s), none of which resolve to a vault note"
        if targets
        else "it contains no [[wikilink]] markers at all"
    )
    issues.append(
        {
            "rule": "citation-style-preservation",
            "severity": "error",
            "note_id": "<vault>",
            "note_path": str(report_path),
            "message": (
                "citation_style is 'wikilink' but the final report cites no vault sources: "
                f"{detail}. A polish/synthesis step likely stripped the source citations. "
                "Restore [[<source-note-id>]] markers for the claims the corpus supports."
            ),
        }
    )


def _check_inline_citations(report_path, report_text: str, issues: list) -> None:
    import re as _re

    has_numbered_ref = bool(_re.search(r"\[\d+(?:\s*,\s*\d+)*\]", report_text))
    has_refs_heading = bool(
        _re.search(
            r"^#{1,6}\s*(sources|references)\b",
            report_text,
            _re.IGNORECASE | _re.MULTILINE,
        )
    )
    if has_numbered_ref and has_refs_heading:
        return
    missing = []
    if not has_numbered_ref:
        missing.append("numbered [N] reference markers")
    if not has_refs_heading:
        missing.append("a Sources/References section heading")
    issues.append(
        {
            "rule": "citation-style-preservation",
            "severity": "error",
            "note_id": "<vault>",
            "note_path": str(report_path),
            "message": (
                "citation_style is 'inline' but the final report is missing "
                f"{' and '.join(missing)}. Restore the inline citation system before "
                "shipping the report."
            ),
        }
    )


def _check_styled_report(conn, report_path, citation_style: str, issues: list) -> None:
    try:
        report_text = report_path.read_text(encoding="utf-8-sig")
    except OSError:
        report_text = ""
    if citation_style == "wikilink":
        _check_wikilink_citations(conn, report_path, report_text, issues)
    elif citation_style == "inline":
        _check_inline_citations(report_path, report_text, issues)


def _lint_citation_style(vault, conn, issues: list, run) -> None:
    # The polish step (15) is instructed by prompt to preserve
    # `[[<source-note-id>]]` markers when citation_style == "wikilink" —
    # they ARE the citation system. Nothing structural enforced that: a
    # synthesizer or polish regression that strips every source wikilink
    # would ship a citation-free report. This rule is the presence-only
    # backstop: at least one citation matching the declared style must
    # survive in the final report. Deliberately NOT a density floor —
    # short reports and quote-heavy sections make density checks
    # false-positive; a separate warning-level rule can add that later.
    citation_style = _declared_citation_style(vault)
    if citation_style not in ("wikilink", "inline"):
        return
    source_count = _scalar_count(
        conn,
        "SELECT COUNT(*) AS c FROM notes n "
        "WHERE n.source IS NOT NULL "
        "AND n.id NOT LIKE '\\_%' ESCAPE '\\' "
        "AND n.type NOT IN ('index','raw','moc')",
    )
    reports_dir = vault.reports_dir
    report_candidates = (
        sorted(
            reports_dir.rglob("final_report*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if reports_dir.exists()
        else []
    )
    # No source notes => nothing to cite; no report => wrapper-report
    # already errors on that. Either way there is nothing to check.
    if source_count <= 0 or not report_candidates:
        return
    _check_styled_report(conn, report_candidates[0], citation_style, issues)


_RAW_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"})


def _check_raw_file(raw_file, note_ids: set, vault, issues: list) -> None:
    if not raw_file.is_file():
        return
    # Only flag known raw extensions; ignore any README etc.
    if raw_file.suffix.lower() not in _RAW_EXTENSIONS:
        return
    if raw_file.stem in note_ids:
        return
    issues.append(
        {
            "rule": "orphaned-raw-files",
            "severity": "warning",
            "note_id": raw_file.stem,
            "note_path": str(raw_file.relative_to(vault.root).as_posix()),
            "message": (
                f"Raw file {raw_file.name} has no matching note in the vault. "
                f"Likely a leftover from an old `note rm` that didn't clean up "
                f"raw files. Delete it manually or let repair handle it."
            ),
        }
    )


def _lint_orphaned_raw(vault, conn, issues: list, run) -> None:
    # Walk output/raw/ and flag files whose stem doesn't match any note
    # id in the vault. These are leftovers from the pre-Batch-2.5 `note rm`
    # which never touched raw files. A cheap disk-leak detector.
    raw_dir = vault.research_dir / "raw"
    if not raw_dir.is_dir():
        return
    note_ids = {r["id"] for r in conn.execute("SELECT id FROM notes")}
    for raw_file in raw_dir.iterdir():
        _check_raw_file(raw_file, note_ids, vault, issues)


def _count_by_tag(conn, tag: str) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT note_id) as c FROM tags WHERE tag = ?",
        (tag,),
    ).fetchone()
    return row["c"] if row else 0


def _count_locus_dicts(vault) -> int:
    try:
        loci_data = json.loads(_run_artifact(vault, "loci.json").read_text(encoding="utf-8"))
        loci_list = loci_data.get("loci", []) if isinstance(loci_data, dict) else loci_data
        return sum(1 for x in loci_list if isinstance(x, dict))
    except (json.JSONDecodeError, OSError):
        return 0


def _check_scaffold_artifact(issues: list, has_output: int, scaffold_count: int, scaffold_md_exists: bool) -> None:
    if has_output <= 0:
        return
    # A scaffold note or scaffold.md file satisfies the scaffold
    # requirement. Either artifact is proof that Layer 0 ran.
    if scaffold_count == 0 and not scaffold_md_exists:
        issues.append(
            {
                "rule": "workflow",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"Vault has {has_output} research-output note(s) "
                    f"but no scaffold artifact (neither a scaffold-tagged note "
                    f"nor output/scaffold.md). Research sessions must produce "
                    f"a scaffold before the draft."
                ),
            }
        )


def _check_interim_artifact(issues: list, loci_json_exists: bool, interim_count: int) -> None:
    # Hyperresearch-specific: if loci.json exists, the run was hyperresearch and
    # must have produced interim notes.
    if loci_json_exists and interim_count == 0:
        issues.append(
            {
                "rule": "workflow",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    "output/loci.json exists but no interim notes found. "
                    "Layer 3 depth investigation was skipped entirely. "
                    "See locus-coverage rule for per-locus details."
                ),
            }
        )


def _check_comparisons_artifact(vault, issues: list, loci_json_exists: bool) -> None:
    # Hyperresearch-specific: if loci.json has 2+ entries, Layer 3.5 must
    # have produced output/comparisons.md. A single locus means
    # there's nothing to compare and the bridge step is legitimately
    # skipped; 2+ loci means the orchestrator needed to reconcile
    # them before drafting, and skipping that step is the failure
    # mode that tanks the insight score.
    if not loci_json_exists:
        return
    locus_count = _count_locus_dicts(vault)
    comparisons_exists = (_run_artifact(vault, "comparisons.md")).exists()
    if locus_count >= 1 and not comparisons_exists:
        issues.append(
            {
                "rule": "workflow",
                "severity": "error",
                "note_id": "<vault>",
                "message": (
                    f"output/loci.json has {locus_count} loci but "
                    "output/comparisons.md is missing. Layer 3.5 "
                    "(cross-locus reconciliation) was skipped. Layer "
                    "3.5 is always-on now — it writes the argumentative "
                    "spine the draft will engage, and single-locus "
                    "runs produce a comparisons.md with that locus's "
                    "committed position as the lone anchor. Spawn the "
                    "orchestrator to produce comparisons.md before the "
                    "next draft."
                ),
            }
        )


def _lint_workflow(vault, conn, issues: list, run) -> None:
    # Detect research sessions that skipped required process artifacts.
    #
    # Hyperresearch required artifacts when a final_report exists:
    #   - output/scaffold.md       (Layer 0 planning document)
    #   - output/loci.json         (Layer 2 deduped loci list, if depth ran)
    #   - interim notes              (Layer 3 depth investigator outputs)
    #   - output/comparisons.md    (Layer 3.5 cross-locus reconciliation,
    #                                 required when loci.json has 2+ entries)
    #
    # The single-pass /research protocol also produces a scaffold note but
    # has no loci/interim/comparisons artifacts. This rule checks scaffold
    # universally and hyperresearch-specific artifacts only when loci.json exists.
    has_research_output = conn.execute("""
        SELECT COUNT(*) as c FROM notes n
        WHERE n.id LIKE '%final_report%'
           OR n.type = 'moc'
           OR n.id IN (SELECT note_id FROM tags WHERE tag = 'synthesis')
    """).fetchone()["c"]
    scaffold_count = _count_by_tag(conn, "scaffold")
    interim_count = _scalar_count(conn, "SELECT COUNT(*) as c FROM notes n WHERE n.type = 'interim'")
    loci_json_exists = _run_artifact(vault, "loci.json").exists()
    _check_scaffold_artifact(
        issues, has_research_output, scaffold_count, _run_artifact(vault, "scaffold.md").exists()
    )
    _check_interim_artifact(issues, loci_json_exists, interim_count)
    _check_comparisons_artifact(vault, issues, loci_json_exists)


def _lint_missing_title(vault, conn, issues: list, run) -> None:
    for row in conn.execute("SELECT id, path FROM notes WHERE title = '' OR title = 'Untitled'"):
        issues.append(
            {
                "rule": "missing-title",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note has no meaningful title.",
            }
        )


def _lint_missing_tags(vault, conn, issues: list, run) -> None:
    for row in conn.execute(
        "SELECT n.id, n.path FROM notes n "
        "WHERE n.type NOT IN ('index','raw') "
        "AND n.id NOT IN (SELECT DISTINCT note_id FROM tags)"
    ):
        issues.append(
            {
                "rule": "missing-tags",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note has no tags.",
            }
        )


def _lint_missing_summary(vault, conn, issues: list, run) -> None:
    for row in conn.execute(
        "SELECT n.id, n.path FROM notes n "
        "WHERE n.type NOT IN ('index','raw') "
        "AND (n.summary IS NULL OR LENGTH(TRIM(n.summary)) = 0)"
    ):
        issues.append(
            {
                "rule": "missing-summary",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note has no summary. Add one for better search and listings.",
            }
        )


def _lint_uncurated(vault, conn, issues: list, run) -> None:
    # Any note that has moved past draft without tier/content_type classification
    # is a curation failure. Exempt: draft notes (expected raw), index/raw/moc
    # types (not sources), and notes whose id starts with _ (auto-generated
    # index notes like _most-linked, _stale, _orphans).
    for row in conn.execute(
        "SELECT n.id, n.path, n.status, n.tier, n.content_type FROM notes n "
        "WHERE n.type NOT IN ('index','raw','moc') "
        "AND n.id NOT LIKE '\\_%' ESCAPE '\\' "
        "AND n.status != 'draft' "
        "AND (n.tier IS NULL OR n.tier = 'unknown' "
        "     OR n.content_type IS NULL OR n.content_type = 'unknown')"
    ):
        missing = []
        if not row["tier"] or row["tier"] == "unknown":
            missing.append("tier")
        if not row["content_type"] or row["content_type"] == "unknown":
            missing.append("content_type")
        issues.append(
            {
                "rule": "uncurated",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": f"Note is {row['status']} but missing {'/'.join(missing)}. Run curation pass.",
            }
        )


def _lint_singleton_tags(vault, conn, issues: list, run) -> None:
    for row in conn.execute("SELECT tag, COUNT(*) as c FROM tags GROUP BY tag HAVING c = 1"):
        issues.append(
            {
                "rule": "singleton-tags",
                "severity": "info",
                "note_id": row["tag"],
                "message": f"Tag '{row['tag']}' is used by only 1 note. Consider merging.",
            }
        )


def _lint_broken_links(vault, conn, issues: list, run) -> None:
    for row in conn.execute(
        "SELECT l.source_id, n.path, l.target_ref, l.line_number "
        "FROM links l JOIN notes n ON l.source_id = n.id "
        "WHERE l.target_id IS NULL"
    ):
        issues.append(
            {
                "rule": "broken-links",
                "severity": "warning",
                "note_id": row["source_id"],
                "note_path": row["path"],
                "line": row["line_number"],
                "message": f"Broken link: [[{row['target_ref']}]]",
            }
        )


def _lint_orphaned_notes(vault, conn, issues: list, run) -> None:
    for row in conn.execute("""
        SELECT n.id, n.path FROM notes n
        WHERE n.type NOT IN ('index', 'raw')
          AND n.id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)
          AND n.id NOT IN (SELECT DISTINCT source_id FROM links)
    """):
        issues.append(
            {
                "rule": "orphaned-notes",
                "severity": "info",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note is orphaned (no links in or out).",
            }
        )


def _lint_duplicate_ids(vault, conn, issues: list, run) -> None:
    for row in conn.execute("SELECT id, COUNT(*) as c FROM notes GROUP BY id HAVING c > 1"):
        issues.append(
            {
                "rule": "duplicate-ids",
                "severity": "error",
                "note_id": row["id"],
                "message": f"Duplicate ID found {row['c']} times.",
            }
        )


def _lint_empty_notes(vault, conn, issues: list, run) -> None:
    for row in conn.execute(
        "SELECT n.id, n.path FROM notes n "
        "JOIN note_content nc ON n.id = nc.note_id "
        "WHERE LENGTH(TRIM(nc.body)) < 10 AND n.type NOT IN ('index')"
    ):
        issues.append(
            {
                "rule": "empty-notes",
                "severity": "info",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note has little or no content.",
            }
        )


def _lint_expired_notes(vault, conn, issues: list, run) -> None:
    from datetime import datetime

    now_iso = datetime.now(UTC).isoformat()
    for row in conn.execute(
        "SELECT id, path, expires FROM notes WHERE expires IS NOT NULL AND expires < ?",
        (now_iso,),
    ):
        issues.append(
            {
                "rule": "expired-notes",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": f"Note expired on {row['expires']}. Review or update.",
            }
        )


def _lint_stale_reviews(vault, conn, issues: list, run) -> None:
    from datetime import datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=vault.config.lint.stale_review_days)).isoformat()
    for row in conn.execute(
        "SELECT id, path, reviewed FROM notes "
        "WHERE reviewed IS NOT NULL AND reviewed < ? AND status = 'evergreen'",
        (cutoff,),
    ):
        issues.append(
            {
                "rule": "stale-reviews",
                "severity": "info",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": f"Last reviewed {row['reviewed'][:10]}. Consider re-reviewing.",
            }
        )


def _lint_verification(vault, conn, issues: list, rules: list) -> None:
    # Phase-5 verification rules: report content vs. vault evidence.
    verification_rules = {"quote-integrity", "numeric-consistency", "retracted-citations"}
    if not (verification_rules & set(rules)):
        return
    report_path, report_text = _latest_report(vault)
    if report_text is None:
        return
    if "quote-integrity" in rules:
        issues.extend(_check_quote_integrity(vault, conn, report_path, report_text))
    if "numeric-consistency" in rules:
        issues.extend(_check_numeric_consistency(vault, conn, report_path, report_text))
    if "retracted-citations" in rules:
        issues.extend(_check_retracted_citations(vault, conn, report_path, report_text))


def _check_guard_postcheck(issues: list, guards: list) -> None:
    # Audit-gate self-certification post-check. For each CRITICAL finding
    # that was marked `fixed_at`, we queued its implied lint rule for
    # re-running via rules_to_run. Now that the full lint pass is done,
    # check whether the rule still emitted errors. If yes, the agent marked
    # a CRITICAL resolved without actually fixing the underlying vault state
    # — emit a self-cert violation error that blocks the save gate.
    if not guards:
        return
    for guard in guards:
        rule_errors = [
            i for i in issues if i.get("rule") == guard["rule"] and i.get("severity") == "error"
        ]
        if rule_errors:
            issues.append(
                {
                    "rule": "audit-gate",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"SELF-CERTIFICATION VIOLATION: CRITICAL [{guard['critical_id']}] "
                        f"was marked `fixed_at` in output/audit_findings.json, but lint "
                        f"rule `{guard['rule']}` still returns {len(rule_errors)} error(s). "
                        f"The finding was '{guard['description']}'. The draft's `fixed_at` "
                        f"marker does not match the vault's actual state — you must fix the "
                        f"underlying issue (not just the bookkeeping). Run "
                        f"`$HPR lint --rule {guard['rule']} -j` to see what's still broken."
                    ),
                }
            )


def _print_lint_issues(issues: list, summary_result: dict) -> None:
    severity_style = {"error": "red bold", "warning": "yellow", "info": "dim"}
    for issue in issues:
        style = severity_style.get(issue.get("severity", "info"), "dim")
        loc = issue.get("note_path", issue.get("note_id", ""))
        line = f" line {issue['line']}" if issue.get("line") else ""
        console.print(f"  [{style}]{issue['rule']}[/] {loc}{line}: {issue['message']}")
    console.print(
        f"\n[bold]Summary:[/] {summary_result['errors']} errors, "
        f"{summary_result['warnings']} warnings, {summary_result['info']} info"
    )


def _report_lint_results(vault, issues: list, json_output: bool) -> None:
    summary_result = {
        "errors": sum(1 for i in issues if i.get("severity") == "error"),
        "warnings": sum(1 for i in issues if i.get("severity") == "warning"),
        "info": sum(1 for i in issues if i.get("severity") == "info"),
        "total": len(issues),
    }
    if json_output:
        output(
            success(
                {"issues": issues, "summary": summary_result},
                count=len(issues),
                vault=str(vault.root),
            ),
            json_mode=True,
        )
        return
    if not issues:
        console.print("[green]Vault is healthy. No issues found.[/]")
        return
    _print_lint_issues(issues, summary_result)


_LINT_CHECKS = (
    ("missing-title", _lint_missing_title),
    ("missing-tags", _lint_missing_tags),
    ("missing-summary", _lint_missing_summary),
    ("audit-gate", _lint_audit_gate),
    ("scaffold-prompt", _lint_scaffold_prompt),
    ("wrapper-report", _lint_wrapper_report),
    ("provenance", _lint_provenance),
    ("locus-coverage", _lint_locus_coverage),
    ("extract-coverage", _lint_extract_coverage),
    ("patch-surgery", _lint_patch_surgery),
    ("instruction-coverage", _lint_instruction_coverage),
    ("citation-style-preservation", _lint_citation_style),
    ("orphaned-raw-files", _lint_orphaned_raw),
    ("workflow", _lint_workflow),
    ("uncurated", _lint_uncurated),
    ("singleton-tags", _lint_singleton_tags),
    ("broken-links", _lint_broken_links),
    ("orphaned-notes", _lint_orphaned_notes),
    ("duplicate-ids", _lint_duplicate_ids),
    ("empty-notes", _lint_empty_notes),
    ("expired-notes", _lint_expired_notes),
    ("stale-reviews", _lint_stale_reviews),
)


@app.callback(invoke_without_command=True)
def lint(
    ctx: typer.Context,
    fix: bool = typer.Option(False, "--fix", help="Auto-fix what's possible"),
    rule: str | None = typer.Option(None, "--rule", "-r", help="Run specific rule only"),
    audit_file: str | None = typer.Option(
        None,
        "--audit-file",
        help=(
            "Path (relative to vault root) to the audit_findings.json file the "
            "audit-gate rule reads. Defaults to output/audit_findings.json. "
            "Ensemble sub-runs pass output/audit_findings-run-{a,b,c}.json."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Health-check the vault."""
    if ctx.invoked_subcommand is not None:
        return

    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()
    conn = vault.db

    issues: list[dict] = []

    rules_to_run = [rule] if rule else list(RULES.keys())

    # Map from audit-gate CRITICAL finding id -> lint rule name that should be
    # re-run to verify the fix actually landed. Populated inside the audit-gate
    # block and consumed at the end of lint() for self-certification detection.
    # Key words in the finding description are mapped to lint rule names.
    audit_gate_guards: list[dict] = []  # [{"critical_id", "rule", "description"}]

    from types import SimpleNamespace

    run = SimpleNamespace(rules=rules_to_run, guards=audit_gate_guards, audit_file=audit_file)
    for _name, _check in _LINT_CHECKS:
        if _name in run.rules:
            _check(vault, conn, issues, run)

    _lint_verification(vault, conn, issues, run.rules)
    _check_guard_postcheck(issues, run.guards)
    _report_lint_results(vault, issues, json_output)
