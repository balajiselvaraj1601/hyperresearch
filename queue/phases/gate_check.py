#!/usr/bin/env python3
"""Check one hyperresearch phase gate. Stdlib only.

Run from anywhere:

    TAG=<vault_tag> PHASE=B1 python3 apps/hyperresearch/queue/phases/gate_check.py

Optional: REGISTRY_TIER=light|full (B1 Replan when it disagrees with the
decomposition). HPR_ROOT overrides the vault directory. With TAG set and no
HPR_ROOT, the vault is the dump topic root for that tag. With neither set,
the default is the apps/hyperresearch directory that contains this file.

Exit 0 pass, 2 conditional pass, 1 hold, 3 replan. One JSON object on stdout.
This process does not call `run step` or `run finish`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SOURCE_MIN = {"light": 10, "full": 45, "premier": 90}
WORD_HIGH = {
    "light": {"short": 2000, "structured": 5000, "argumentative": 10000},
    "full": {"short": 2000, "structured": 5000, "argumentative": 10000},
    "premier": {"short": 2000, "structured": 8000, "argumentative": 16000},
}
FULL_ONLY = {"B3", "B4", "B5", "B6", "B7", "B8", "B9", "B11", "B12", "B13", "B14", "B14.5"}
LIGHT_SEQUENCE = ["B1", "B2", "B10", "B15", "B16"]
FULL_SEQUENCE = [
    "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10",
    "B11", "B12", "B13", "B14", "B14.5", "B15", "B16", "A4",
]
CRITICS = ("dialectic", "depth", "width", "instruction")
SHIMS = ("research.md", "drafting.md", "critics.md", "polish.md")


def vault_root() -> Path:
    """Topic vault that holds output/runs/<tag>. HPR_ROOT overrides it."""
    override = os.environ.get("HPR_ROOT")
    if override:
        return Path(override)
    tag = os.environ.get("TAG", "").strip()
    if tag:
        src = Path(__file__).resolve().parents[2] / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from hyperresearch.core.locations import topic_root

        return topic_root(tag)
    here = Path(__file__).resolve()
    candidate = here.parents[2]
    if (candidate / "pyproject.toml").is_file():
        return candidate
    raise SystemExit("set HPR_ROOT to the topic vault")


def load_json(path: Path):
    """Parse JSON, accepting a leading BOM. Return None when unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def hpr(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the vault CLI. The system shim is not used."""
    return subprocess.run(
        ["uv", "run", "hyperresearch", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def note_rows(root: Path, tag: str, extra: list[str] | None = None) -> tuple[list | None, str]:
    """Return note-list rows, or None plus an error string."""
    proc = hpr(root, ["note", "list", "--tag", tag, "--all", "-j", *(extra or [])])
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout)[-400:]
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, "note list did not return JSON"
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None, "note list JSON has no data list"
    return rows, ""


def findings_of(path: Path) -> list | None:
    """Findings list from a critic file, or None when the file is bad."""
    data = load_json(path)
    if data is None:
        return None
    if isinstance(data, dict):
        data = data.get("findings", [])
    if not isinstance(data, list):
        return None
    return data


def named_dispositions(log: dict) -> int:
    """Patch-log entries that name a finding. A reason-only skip counts as zero."""
    count = 0
    for key in ("applied", "skipped", "conflicts", "orchestrator_escalated"):
        for entry in log.get(key) or []:
            if isinstance(entry, dict) and entry.get("finding"):
                count += 1
    return count


def critical_count(run: Path) -> int:
    """Critical critic findings across the four critic files."""
    total = 0
    for name in CRITICS:
        rows = findings_of(run / f"critic-findings-{name}.json")
        if not rows:
            continue
        total += sum(1 for row in rows if isinstance(row, dict) and row.get("severity") == "critical")
    return total


class Gate:
    """Accumulates criterion results for one phase."""

    def __init__(self, phase: str, tag: str) -> None:
        self.phase = phase
        self.tag = tag
        self.criteria: list[dict] = []
        self.replan = False

    def add(self, criterion_id: str, ok: bool, evidence: str, *, advisory: bool = False) -> None:
        result = "met" if ok else "not_met"
        self.criteria.append(
            {
                "id": criterion_id,
                "result": result,
                "advisory": advisory,
                "evidence": evidence,
            }
        )

    def finish(self, name: str, nxt: str) -> int:
        mandatory = [row for row in self.criteria if not row["advisory"]]
        failed = [row for row in mandatory if row["result"] != "met"]
        advisory_failed = [row for row in self.criteria if row["advisory"] and row["result"] != "met"]
        if self.replan:
            decision = "Replan"
            code = 3
        elif failed:
            decision = "Hold"
            code = 1
        elif advisory_failed:
            decision = "Conditional pass"
            code = 2
        else:
            decision = "Pass"
            code = 0
        print(
            json.dumps(
                {
                    "phase": self.phase,
                    "name": name,
                    "vault_tag": self.tag,
                    "decision": decision,
                    "criteria": self.criteria,
                    "next": nxt if code in (0, 2) else self.phase,
                    "verifier": "gate-check",
                },
                indent=2,
            )
        )
        return code


def tier_of(run: Path, manifest: dict) -> str:
    """Declared pipeline tier, else the manifest profile."""
    decomp = load_json(run / "prompt-decomposition.json")
    if isinstance(decomp, dict) and isinstance(decomp.get("pipeline_tier"), str):
        return decomp["pipeline_tier"]
    profile = manifest.get("profile")
    return profile if isinstance(profile, str) else "full"


def next_phase(phase: str, tier: str) -> str:
    """Next phase id for this tier. Full-only phases are already skipped by the caller."""
    sequence = LIGHT_SEQUENCE if tier == "light" else FULL_SEQUENCE
    if phase not in sequence:
        return ""
    index = sequence.index(phase)
    if index + 1 >= len(sequence):
        return "A4" if phase != "A4" else ""
    return sequence[index + 1]


def check_common(gate: Gate, run: Path, manifest: dict) -> None:
    """Entry facts shared by every research phase."""
    status = manifest.get("status")
    blocked = manifest.get("blocked_on")
    ok_status = status in ("running", "blocked", "done") and (
        status != "blocked" or blocked in ("verify", "budget", "human-challenges", None)
    )
    gate.add("E0", bool(ok_status), f"status={status} blocked_on={blocked}")
    query = run / "query.md"
    gate.add("E2", query.is_file() and bool(query.read_text(encoding="utf-8").strip()), str(query))


def check_b1(gate: Gate, run: Path) -> None:
    decomp_path = run / "prompt-decomposition.json"
    decomp = load_json(decomp_path)
    ok = isinstance(decomp, dict) and all(
        decomp.get(key) for key in ("pipeline_tier", "response_format", "citation_style", "levers")
    )
    gate.add("X1", ok, str(decomp_path))
    matrix = run / "temp" / "coverage-matrix.md"
    text = matrix.read_text(encoding="utf-8") if matrix.is_file() else ""
    gate.add("X2", matrix.is_file() and "Gap? = YES" not in text, str(matrix))
    missing = [name for name in SHIMS if not (run / "shims" / name).is_file() or (run / "shims" / name).stat().st_size == 0]
    gate.add("X3", not missing, "missing " + ",".join(missing) if missing else str(run / "shims"))
    scaffold = run / "scaffold.md"
    body = scaffold.read_text(encoding="utf-8") if scaffold.is_file() else ""
    gate.add("X4", "tier rationale" in body.lower(), str(scaffold))
    registry = os.environ.get("REGISTRY_TIER", "").strip()
    if registry and isinstance(decomp, dict) and decomp.get("pipeline_tier") not in (registry, ""):
        gate.replan = True
        gate.add("X5", False, f"decomposition={decomp.get('pipeline_tier')} registry={registry}")
    else:
        gate.add("X5", True, registry or "registry tier not supplied")


def check_b2(gate: Gate, root: Path, run: Path, tag: str, tier: str, profile: str) -> None:
    rows, err = note_rows(root, tag)
    minimum = SOURCE_MIN.get(profile if profile in SOURCE_MIN else tier, SOURCE_MIN["full"])
    count = len(rows) if rows is not None else -1
    gaps = run / "temp" / "coverage-gaps.md"
    gap_text = gaps.read_text(encoding="utf-8") if gaps.is_file() else ""
    if rows is None:
        gate.add("X1", False, err)
    elif count >= minimum:
        gate.add("X1", True, f"notes={count} min={minimum}")
    elif count >= minimum / 2 and gaps.is_file():
        gate.add("X1", False, f"notes={count} min={minimum}; shortfall listed", advisory=True)
    else:
        gate.add("X1", False, f"notes={count} min={minimum}")
    uncovered = 0
    for line in gap_text.splitlines():
        if "|" in line and re.search(r"(?i)\buncovered\b", line):
            uncovered += 1
    gate.add("X2", gaps.is_file() and uncovered == 0, f"uncovered_rows={uncovered}")
    gate.add("X3", gaps.is_file() and bool(gap_text.strip()), str(gaps))
    claims = list(run.glob("claims-*.json")) + list((run / "temp").glob("claims-*.json"))
    gate.add("X4", bool(claims), f"claims_files={len(claims)}")
    if tier != "light":
        audit = run / "temp" / "redundancy-audit.md"
        gate.add("X5", (not claims) or audit.is_file(), str(audit))


def check_b3(gate: Gate, run: Path) -> None:
    graph = load_json(run / "temp" / "contradiction-graph.json")
    consensus = load_json(run / "temp" / "consensus-claims.json")
    gate.add("X1", isinstance(graph, list), str(run / "temp" / "contradiction-graph.json"))
    gate.add("X2", isinstance(consensus, list), str(run / "temp" / "consensus-claims.json"))
    if graph == [] and consensus == []:
        gate.add("X3", False, "both arrays empty; confirm the corpus is univocal", advisory=True)


def check_b4(gate: Gate, run: Path, profile: str) -> None:
    path = run / "loci.json"
    data = load_json(path)
    loci = data.get("loci") if isinstance(data, dict) else data
    if not isinstance(loci, list):
        gate.add("X1", False, str(path))
        return
    skip = data.get("skip_loci") if isinstance(data, dict) else None
    gate.add("X1", bool(loci) or bool(skip), str(path))
    dialectical = any(isinstance(row, dict) and row.get("flavor") == "dialectical" for row in loci)
    gate.add("X2", dialectical or bool(skip), "dialectical locus or skip_loci")
    budgets_ok = all(
        isinstance(row, dict) and isinstance(row.get("source_budget"), (int, float))
        for row in loci
    )
    gate.add("X3", budgets_ok, "source_budget on every locus")
    cap = 10 if profile == "premier" else 6
    gate.add("X4", len(loci) <= cap, f"count={len(loci)} cap={cap}")


def check_b5(gate: Gate, root: Path, tag: str) -> None:
    rows, err = note_rows(root, tag, ["--type", "interim"])
    if rows is None:
        gate.add("X1", False, err)
        return
    if not rows:
        gate.add("X1", False, "no interim notes")
        return
    missing = 0
    shown = 0
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        shown += 1
        proc = hpr(root, ["note", "show", str(row["id"]), "-j"])
        body = proc.stdout if proc.returncode == 0 else ""
        if "## Committed position" not in body:
            missing += 1
    gate.add("X1", shown > 0, f"interim_notes={shown}")
    gate.add("X2", missing == 0, f"missing_committed_position={missing}")


def check_b6(gate: Gate, run: Path) -> None:
    path = run / "comparisons.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    gate.add("X1", len(text.split()) > 40, str(path))


def check_b7(gate: Gate, run: Path, profile: str) -> None:
    path = run / "temp" / "source-tensions.json"
    data = load_json(path)
    rows = data.get("tensions") if isinstance(data, dict) else data
    low, high = (4, 9) if profile == "premier" else (3, 7)
    ok = isinstance(rows, list) and low <= len(rows) <= high
    gate.add("X1", ok, f"{path} count={len(rows) if isinstance(rows, list) else 'bad'} range={low}-{high}")
    if isinstance(rows, list):
        complete = all(
            isinstance(row, dict) and row.get("decision_relevance") and row.get("resolution", row.get("committed_resolution"))
            for row in rows
        )
        gate.add("X2", complete, "resolution and decision_relevance")


def check_b8(gate: Gate, run: Path) -> None:
    path = run / "corpus-critic-gaps.json"
    data = load_json(path)
    gaps = data.get("gaps") if isinstance(data, dict) else data
    ok = isinstance(gaps, list) and all(isinstance(row, dict) and row.get("id") for row in gaps)
    gate.add("X1", ok, str(path))
    results = run / "temp" / "corpus-critic-results.md"
    gate.add("X2", results.is_file(), str(results))


def check_b9(gate: Gate, run: Path, profile: str) -> None:
    path = run / "temp" / "evidence-digest.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    floor = 50 if profile == "premier" else 30
    claims = len(re.findall(r"(?i)source_note_id", text))
    gate.add("X1", path.is_file() and claims > 0, f"source_note_id_marks={claims}")
    gate.add("X2", claims >= floor, f"floor={floor}", advisory=True)


def check_b10(gate: Gate, run: Path, tag: str, tier: str, profile: str) -> None:
    report = run.parents[1] / "reports" / tag / f"final_report_{tag}.md"
    # run is output/runs/<tag>, parents[0]=runs, parents[1]=output
    if tier == "light":
        gate.add("X1", report.is_file(), str(report))
        return
    drafts = [run / "temp" / f"draft-{name}.md" for name in ("a", "b", "c")]
    missing = [str(path) for path in drafts if not path.is_file()]
    gate.add("X1", not missing, "missing " + ",".join(missing) if missing else "three drafts")
    short = [path.name for path in drafts if path.is_file() and path.stat().st_size < 500]
    gate.add("X2", not short, "short " + ",".join(short) if short else "length floor")
    wrote_report = (
        report.is_file()
        and all(path.is_file() for path in drafts)
        and report.stat().st_mtime > max(path.stat().st_mtime for path in drafts)
    )
    gate.add("X3", not wrote_report, str(report))


def check_b11(gate: Gate, run: Path, tag: str, profile: str) -> None:
    report = run.parents[1] / "reports" / tag / f"final_report_{tag}.md"
    pass1 = run / "temp" / "synthesis-pass1.md"
    gate.add("X1", pass1.is_file(), str(pass1))
    text = report.read_text(encoding="utf-8") if report.is_file() else ""
    gate.add("X2", report.is_file() and bool(text.strip()), str(report))
    decomp = load_json(run / "prompt-decomposition.json")
    fmt = decomp.get("response_format") if isinstance(decomp, dict) else None
    high = WORD_HIGH.get(profile, WORD_HIGH["full"]).get(fmt or "", 10000)
    words = len(text.split())
    gate.add("X3", bool(text) and words <= high, f"words={words} high={high}")
    headings = decomp.get("required_section_headings") if isinstance(decomp, dict) else []
    missing = [heading for heading in headings or [] if heading not in text]
    leak = "## User Prompt (VERBATIM" in text or text.startswith("---\n")
    gate.add("X4", not missing and not leak, f"missing_headings={missing} leak={leak}")


def check_b12(gate: Gate, run: Path) -> None:
    empty = 0
    for name in CRITICS:
        path = run / f"critic-findings-{name}.json"
        rows = findings_of(path)
        gate.add(f"X-{name}", rows is not None, str(path))
        if rows == []:
            empty += 1
    if empty == 4:
        gate.add("X-empty", False, "all four finding arrays are empty")
    elif empty:
        gate.add("X-empty", False, f"empty_files={empty}", advisory=True)


def check_b13(gate: Gate, run: Path) -> None:
    path = run / "temp" / "post-critic-fetch-log.md"
    gate.add("X1", path.is_file() and bool(path.read_text(encoding="utf-8").strip()), str(path))


def check_b14(gate: Gate, run: Path) -> None:
    path = run / "patch-log.json"
    log = load_json(path)
    if not isinstance(log, dict):
        gate.add("X1", False, str(path))
        return
    handled = named_dispositions(log)
    gate.add("X1", "total_findings" in log and handled > 0, f"named_dispositions={handled}")
    criticals = critical_count(run)
    gate.add("X2", handled >= criticals, f"criticals={criticals} dispositions={handled}")


def check_b145(gate: Gate, run: Path, manifest: dict) -> None:
    pairs = load_json(run / "cite-check-pairs.json")
    findings = load_json(run / "cite-check-findings.json")
    gate.add("X1", pairs is not None and findings is not None, str(run / "cite-check-findings.json"))
    rows = findings.get("findings") if isinstance(findings, dict) else findings
    criticals = [row for row in rows or [] if isinstance(row, dict) and row.get("severity") == "critical"]
    patch = load_json(run / "cite-check-patch-log.json")
    if criticals:
        handled = named_dispositions(patch) if isinstance(patch, dict) else 0
        gate.add("X2", handled >= len(criticals), f"cite_criticals={len(criticals)} dispositions={handled}")
    else:
        gate.add("X2", True, "no critical cite findings")
    status = (manifest.get("steps") or {}).get("14.5", {}).get("status")
    gate.add("X3", status == "done", f"step 14.5 status={status}")


def check_b15(gate: Gate, root: Path, run: Path) -> None:
    path = run / "polish-log.json"
    log = load_json(path)
    stub = log == {"applied": [], "escalations": []}
    populated = isinstance(log, dict) and not stub and ("applied" in log or "escalations" in log)
    gate.add("X1", populated, str(path) + (" stub" if stub else ""))
    for rule in ("wrapper-report", "locus-coverage", "scaffold-prompt", "patch-surgery"):
        proc = hpr(root, ["lint", "--rule", rule, "-j"])
        gate.add(f"X3-{rule}", proc.returncode == 0, f"exit={proc.returncode}")


def check_b16(gate: Gate, run: Path) -> None:
    rec = load_json(run / "readability-recommendations.json")
    decisions = load_json(run / "readability-decisions.json")
    gate.add("X1", rec is not None, str(run / "readability-recommendations.json"))
    applied = decisions.get("applied") if isinstance(decisions, dict) else None
    skipped = decisions.get("skipped") if isinstance(decisions, dict) else None
    ok = isinstance(decisions, dict) and (bool(applied) or (isinstance(skipped, list) and skipped and not applied))
    # all skipped is ok; at least one applied is ok; empty both is not
    if isinstance(decisions, dict) and not applied and isinstance(skipped, list) and skipped:
        ok = True
    if isinstance(decisions, dict) and applied:
        ok = True
    gate.add("X2", bool(ok), str(run / "readability-decisions.json"))


def check_a4(gate: Gate, manifest: dict, run: Path, tag: str) -> None:
    verify = manifest.get("verify") if isinstance(manifest.get("verify"), dict) else {}
    gate.add("X1", manifest.get("status") == "done" and verify.get("passed") is True, f"status={manifest.get('status')} failed={verify.get('failed_checks')}")
    report = run.parents[1] / "reports" / tag / f"final_report_{tag}.md"
    gate.add("X2", report.is_file(), str(report))


def main() -> int:
    tag = os.environ.get("TAG", "").strip()
    phase = os.environ.get("PHASE", "").strip()
    if not tag or not phase:
        print("TAG and PHASE are required", file=sys.stderr)
        return 1
    root = vault_root()
    run = root / "output" / "runs" / tag
    manifest = load_json(run / "run.json")
    if not isinstance(manifest, dict):
        print(json.dumps({"phase": phase, "decision": "Hold", "criteria": [{"id": "E0", "result": "not_met", "evidence": str(run / "run.json")}]}))
        return 1
    profile = manifest.get("profile") if isinstance(manifest.get("profile"), str) else "full"
    tier = tier_of(run, manifest)
    gate = Gate(phase, tag)
    if phase in FULL_ONLY and tier == "light":
        nxt = "B10" if phase in {"B3", "B4", "B5", "B6", "B7", "B8", "B9"} else "B15"
        print(json.dumps({"phase": phase, "vault_tag": tag, "decision": "Pass", "skipped": True, "reason": "light tier", "verifier": "gate-check", "next": nxt}))
        return 0
    check_common(gate, run, manifest)
    if phase == "B1":
        check_b1(gate, run)
    elif phase == "B2":
        check_b2(gate, root, run, tag, tier, profile)
    elif phase == "B3":
        check_b3(gate, run)
    elif phase == "B4":
        check_b4(gate, run, profile)
    elif phase == "B5":
        check_b5(gate, root, tag)
    elif phase == "B6":
        check_b6(gate, run)
    elif phase == "B7":
        check_b7(gate, run, profile)
    elif phase == "B8":
        check_b8(gate, run)
    elif phase == "B9":
        check_b9(gate, run, profile)
    elif phase == "B10":
        check_b10(gate, run, tag, tier, profile)
    elif phase == "B11":
        check_b11(gate, run, tag, profile)
    elif phase == "B12":
        check_b12(gate, run)
    elif phase == "B13":
        check_b13(gate, run)
    elif phase == "B14":
        check_b14(gate, run)
    elif phase == "B14.5":
        check_b145(gate, run, manifest)
    elif phase == "B15":
        check_b15(gate, root, run)
    elif phase == "B16":
        check_b16(gate, run)
    elif phase == "A4":
        check_a4(gate, manifest, run, tag)
    else:
        print(f"unknown PHASE {phase}", file=sys.stderr)
        return 1
    return gate.finish(phase, next_phase(phase, tier) if phase != "A4" else "")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired as exc:
        print(json.dumps({"decision": "Hold", "criteria": [{"id": "CLI", "result": "not_met", "evidence": f"timeout {exc.cmd}"}]}))
        sys.exit(1)
