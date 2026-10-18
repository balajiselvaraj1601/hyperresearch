"""Independence audit — syndicated copies must not multiply consensus.

"3+ independent sources agree" is the pipeline's consensus rule, but a wire
story republished by five outlets is ONE source wearing five outfits.
This module clusters derivative sources three ways:

  url     — identical canonical URL (scheme/www/trailing-slash/UTM stripped)
  body    — near-duplicate bodies (>=0.7 MinHash-verified Jaccard, reusing
            core/similarity.py)
  wire    — shared wire-service boilerplate (PRNewswire, Business Wire, ...)
            in the opening of the text, same story cluster by title overlap

Scores: cluster root (earliest fetched) keeps independence 1.0; members get
1/cluster_size. Unclustered notes get 1.0. Stored on notes.independence
(DB-cache, recomputable) and consumed by step 3's consensus counting and
the quality composite.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from hyperresearch.core.similarity import jaccard, shingle

WIRE_MARKERS = (
    "prnewswire",
    "pr newswire",
    "business wire",
    "businesswire",
    "globe newswire",
    "globenewswire",
    "(reuters)",
    "(ap)",
    "associated press",
    "accesswire",
    "newsfile corp",
)

_TRACKING_PARAMS_RE = re.compile(r"^(utm_|fbclid|gclid|ref$|source$)")
NEAR_DUP_THRESHOLD = 0.7


def canonical_url(url: str) -> str:
    """Normalize scheme/host/path/query so syndication mirrors collide."""
    p = urlparse(url.strip().lower())
    host = p.netloc.removeprefix("www.")
    path = p.path.rstrip("/")
    query = urlencode(
        sorted((k, v) for k, v in parse_qsl(p.query) if not _TRACKING_PARAMS_RE.match(k))
    )
    return urlunparse(("https", host, path, "", query, ""))


def _wire_signature(body: str, title: str) -> str | None:
    """Wire-marker + body-opening signature for press-release clustering.

    Keyed on the body head, NOT the title — outlets retitle syndicated
    copy, but the wire text itself opens identically.
    """
    head = (body or "")[:1500].lower()
    marker = next((m for m in WIRE_MARKERS if m in head), None)
    if marker is None:
        return None
    tokens = re.findall(r"[a-z0-9]{4,}", head)[:10]
    return f"{marker}|{' '.join(tokens)}"


def _uf_find(parent: dict, x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _uf_union(parent: dict, cluster_kind: dict, a: str, b: str, kind: str) -> None:
    ra, rb = _uf_find(parent, a), _uf_find(parent, b)
    if ra != rb:
        parent[rb] = ra
    cluster_kind[frozenset((a, b))] = kind


def _load_source_rows(conn, tag: str | None) -> list:
    query = (
        "SELECT n.id, n.source, n.title, n.created, nc.body_plain "
        "FROM notes n JOIN note_content nc ON nc.note_id = n.id "
        "WHERE n.source IS NOT NULL AND n.type NOT IN ('index')"
    )
    params: tuple = ()
    if tag:
        query += " AND n.id IN (SELECT note_id FROM tags WHERE tag = ?)"
        params = (tag,)
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def _cluster_by_url(rows: list, parent: dict, cluster_kind: dict) -> None:
    """1. Canonical-URL identity."""
    by_url: dict[str, list[dict]] = {}
    for r in rows:
        by_url.setdefault(canonical_url(r["source"]), []).append(r)
    for group in by_url.values():
        for other in group[1:]:
            _uf_union(parent, cluster_kind, group[0]["id"], other["id"], "url")


def _cluster_by_wire(rows: list, parent: dict, cluster_kind: dict) -> None:
    """2. Wire-service signature."""
    by_wire: dict[str, list[dict]] = {}
    for r in rows:
        sig = _wire_signature(r["body_plain"], r["title"])
        if sig:
            by_wire.setdefault(sig, []).append(r)
    for group in by_wire.values():
        for other in group[1:]:
            _uf_union(parent, cluster_kind, group[0]["id"], other["id"], "wire")


def _cluster_near_dup(rows: list, parent: dict, cluster_kind: dict, shingle_size: int) -> None:
    """3. Near-duplicate bodies (pairwise Jaccard on shingles; vaults are
    small enough per-tag, and dedup's MinHash/LSH path exists for scale)."""
    shingles = {r["id"]: shingle(r["body_plain"] or "", n=shingle_size) for r in rows}
    ids = [r["id"] for r in rows]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if _uf_find(parent, ids[i]) == _uf_find(parent, ids[j]):
                continue
            if jaccard(shingles[ids[i]], shingles[ids[j]]) >= NEAR_DUP_THRESHOLD:
                _uf_union(parent, cluster_kind, ids[i], ids[j], "body")


def _score_cluster(conn, members: list, cluster_kind: dict, clusters: list) -> int:
    """Score one cluster; root = earliest fetched (the upstream original)."""
    if len(members) == 1:
        conn.execute("UPDATE notes SET independence = 1.0 WHERE id = ?", (members[0]["id"],))
        return 1
    members.sort(key=lambda r: r["created"] or "")
    root = members[0]
    share = round(1.0 / len(members), 4)
    conn.execute("UPDATE notes SET independence = 1.0 WHERE id = ?", (root["id"],))
    idset = {m["id"] for m in members}
    kinds = sorted({k for pair, k in cluster_kind.items() if pair <= idset})
    for m in members[1:]:
        conn.execute("UPDATE notes SET independence = ? WHERE id = ?", (share, m["id"]))
    clusters.append(
        {
            "root": root["id"],
            "members": [m["id"] for m in members[1:]],
            "size": len(members),
            "kind": "+".join(kinds) or "mixed",
        }
    )
    return len(members)


def _materialize_clusters(conn, rows: list, parent: dict, cluster_kind: dict) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(_uf_find(parent, r["id"]), []).append(r)
    clusters = []
    scored = 0
    for members in groups.values():
        scored += _score_cluster(conn, members, cluster_kind, clusters)
    conn.commit()
    return {"scored": scored, "clusters": clusters}


def compute_independence(vault, tag: str | None = None) -> dict:
    """Cluster derivative sources, write independence scores. Returns summary."""
    conn = vault.db
    rows = _load_source_rows(conn, tag)

    # Union-find over note ids
    parent: dict[str, str] = {r["id"]: r["id"] for r in rows}
    cluster_kind: dict[frozenset, str] = {}

    _cluster_by_url(rows, parent, cluster_kind)
    _cluster_by_wire(rows, parent, cluster_kind)
    _cluster_near_dup(rows, parent, cluster_kind, vault.config.dedup.shingle_size)
    return _materialize_clusters(conn, rows, parent, cluster_kind)
