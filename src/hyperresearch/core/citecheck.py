"""Cite-check — does each citation actually support its sentence?

The FACT half of research quality, self-measured before ship instead of by
an external benchmark. Three layers:

1. `extract_pairs(report_text, conn)` — pure parsing. Splits the report into
   sentences and binds each citation marker to its sentence, for BOTH
   citation styles: numbered `[N]` (resolved through the `## Sources`
   section) and `[[note-id]]` wikilinks.

2. `triage_pairs(pairs, conn)` — mechanical tier. A pair auto-passes when
   the sentence's numbers or a long word-overlap window appear in the cited
   note's claims (`quoted_support` / `numbers`) — no LLM needed for the
   bulk. The remainder is marked `needs-llm` for the cite-checker agent.

3. The `hyperresearch-cite-checker` agent (step 14.5) verifies the
   needs-llm tail against the actual note bodies and emits findings the
   patcher applies. Verdicts: supported | partially-supported |
   unsupported | wrong-source.
"""

from __future__ import annotations

import json
import re

from hyperresearch.core.patterns import WIKI_LINK_RE

# Sentence split: period/question/exclamation followed by space+capital, or newline.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z一-鿿])|\n+")
_NUMBERED_CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_SOURCES_ENTRY_RE = re.compile(r"^\s*\[(\d{1,3})\]\s+(.+)$")
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*%?")

# Sentences carrying these are checked at 100% regardless of sampling.
_STRONG_MARKERS = ("%", "$", "billion", "million", "increase", "decrease", "grew", "fell")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def parse_sources_section(report_text: str, conn) -> dict[str, str | None]:
    """Map `[N]` -> note_id by matching Sources-section URLs/titles to the vault."""
    mapping: dict[str, str | None] = {}
    for num, rest in _source_entries(report_text):
        mapping[num] = _resolve_source_entry(rest, conn)
    return mapping


def _source_entries(report_text: str):
    """Yield (num, rest) entries from the report's Sources/References section."""
    in_sources = False
    for line in report_text.splitlines():
        if re.match(r"^##\s+(Sources|References)\b", line, re.IGNORECASE):
            in_sources = True
            continue
        if in_sources and line.startswith("## "):
            break
        if not in_sources:
            continue
        m = _SOURCES_ENTRY_RE.match(line)
        if not m:
            continue
        yield m.group(1), m.group(2)


def _resolve_source_entry(rest: str, conn) -> str | None:
    """Match one Sources entry to a vault note, by URL then title."""
    note_id = _source_note_by_url(rest, conn)
    if note_id is not None:
        return note_id
    return _source_note_by_title(rest, conn)


def _source_note_by_url(rest: str, conn) -> str | None:
    url_m = re.search(r"https?://\S+", rest)
    if not url_m:
        return None
    url = url_m.group(0).rstrip(".,)")
    row = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    if row:
        return row["note_id"]
    return None


def _source_note_by_title(rest: str, conn) -> str | None:
    title = rest.split("http")[0].strip(" .–-")
    if not title:
        return None
    row = conn.execute("SELECT id FROM notes WHERE title = ? COLLATE NOCASE", (title,)).fetchone()
    if row:
        return row["id"]
    return None


def extract_pairs(report_text: str, conn) -> list[dict]:
    """All (sentence, note_id) citation bindings in the report.

    Pairs whose citation can't be resolved to a vault note get
    note_id=None — those are findings in themselves (dangling citation).
    """
    numbered_map = parse_sources_section(report_text, conn)
    known_ids = {row["id"] for row in conn.execute("SELECT id FROM notes")}

    # Strip the Sources section from the checked body
    body = re.split(r"^##\s+(?:Sources|References)\b", report_text, maxsplit=1, flags=re.M | re.I)[
        0
    ]

    pairs: list[dict] = []
    for sentence in _split_sentences(body):
        for note_id in _cited_in_sentence(sentence, numbered_map, known_ids):
            pairs.append(_pair_dict(sentence, note_id))
    return pairs


def _cited_in_sentence(sentence: str, numbered_map: dict, known_ids: set) -> list[str | None]:
    """All citation targets bound in one sentence."""
    cited: list[str | None] = []
    for m in _NUMBERED_CITE_RE.finditer(sentence):
        for num in re.split(r"\s*,\s*", m.group(1)):
            if num in numbered_map:
                cited.append(numbered_map[num])
    for m in WIKI_LINK_RE.finditer(sentence):
        target = m.group(1).strip()
        cited.append(target if target in known_ids else None)
    return cited


def _pair_dict(sentence: str, note_id: str | None) -> dict:
    return {
        "sentence": sentence,
        "note_id": note_id,
        "numbers": _NUMBER_RE.findall(sentence),
        "strong": any(k in sentence.lower() for k in _STRONG_MARKERS)
        or bool(_NUMBER_RE.search(sentence)),
    }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def triage_pairs(pairs: list[dict], conn) -> dict:
    """Mechanical verification tier.

    Verdicts per pair:
      dangling            — citation resolves to no vault note (finding)
      supported-mechanical — sentence numbers / long overlap found in the
                            cited note's claims (auto-pass)
      needs-llm           — the cite-checker agent must judge it
    """
    claims_by_note: dict[str, list[dict]] = {}

    supported = 0
    dangling = 0
    needs_llm = []
    for pair in pairs:
        if pair["note_id"] is None:
            pair["verdict"] = "dangling"
            dangling += 1
            continue
        blob = _claims_blob(conn, pair["note_id"], claims_by_note)
        if _pair_supported(pair, blob):
            pair["verdict"] = "supported-mechanical"
            supported += 1
        else:
            pair["verdict"] = "needs-llm"
            needs_llm.append(pair)

    return {
        "total": len(pairs),
        "supported_mechanical": supported,
        "dangling": dangling,
        "needs_llm": len(needs_llm),
        "pairs": pairs,
    }


def _claims_blob(conn, note_id: str, cache: dict) -> str:
    """Normalized concatenation of a note's claims (memoized per call)."""
    if note_id not in cache:
        rows = conn.execute(
            "SELECT claim, quoted_support, numbers FROM claims WHERE note_id = ?",
            (note_id,),
        ).fetchall()
        cache[note_id] = [dict(r) for r in rows]
    return _norm(
        " ".join(
            (c["claim"] or "") + " " + (c["quoted_support"] or "") + " " + (c["numbers"] or "")
            for c in cache[note_id]
        )
    )


def _pair_supported(pair: dict, blob: str) -> bool:
    """True when the pair's numbers or a 6-word shingle appear in the blob."""
    if not blob:
        return False
    nums = [n for n in pair["numbers"] if len(n.replace(",", "")) >= 2]
    if nums:
        return all(n.replace(",", "") in blob.replace(",", "") for n in nums)
    # Long word-overlap window: any 6-consecutive-word shingle of the
    # sentence found in the claims blob
    words = _norm(pair["sentence"]).split()
    return any(" ".join(words[i : i + 6]) in blob for i in range(len(words) - 5))


def sample_needs_llm(pairs: list[dict], sample_rate: float = 0.6) -> list[dict]:
    """Deterministic sampling of the LLM tier: 100% of strong (number-bearing)
    sentences, every k-th of the rest. No RNG — reproducible across resumes."""
    out = []
    weak_kept = 0
    weak_seen = 0
    keep_every = max(1, round(1 / sample_rate)) if sample_rate > 0 else 0
    for pair in pairs:
        if pair.get("verdict") != "needs-llm":
            continue
        if pair["strong"]:
            out.append(pair)
        elif keep_every:
            weak_seen += 1
            if weak_seen % keep_every == 0:
                out.append(pair)
                weak_kept += 1
    return out


def write_pairs_file(vault, vault_tag: str, report_path, sample_rate: float = 0.6) -> dict:
    """Extract + triage + sample; write cite-check-pairs.json into the run dir."""
    report_text = report_path.read_text(encoding="utf-8-sig")
    pairs = extract_pairs(report_text, vault.db)
    triaged = triage_pairs(pairs, vault.db)
    to_check = sample_needs_llm(triaged["pairs"], sample_rate)

    run_dir = vault.run_dir(vault_tag)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "report": str(report_path),
        "summary": {k: v for k, v in triaged.items() if k != "pairs"},
        "sampled_for_llm": to_check,
        "dangling": [p for p in triaged["pairs"] if p["verdict"] == "dangling"],
    }
    (run_dir / "cite-check-pairs.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out
