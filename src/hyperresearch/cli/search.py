"""Search CLI — full-text search across all notes."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def _validate_search_enum(value, enum_cls, flag: str, code: str, json_output: bool) -> None:
    """Validate an enum filter up-front, reporting INVALID_* and exiting 1."""
    if value is None:
        return
    try:
        enum_cls(value)
    except ValueError:
        valid = ", ".join(v.value for v in enum_cls)
        if json_output:
            output(
                error(f"Invalid {flag} '{value}'. Must be one of: {valid}", code), json_mode=True
            )
        else:
            console.print(f"[red]Invalid {flag} '{value}'.[/] Must be one of: {valid}")
        raise typer.Exit(1)


def _open_search_vault(json_output: bool):
    """Discover the vault or report NO_VAULT and exit 1."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    vault.auto_sync()
    return vault


def _run_fts(
    vault,
    query: str,
    filters,
    limit: int,
    offset: int,
    ranking: dict,
    ranked: bool,
    json_output: bool,
) -> list:
    from hyperresearch.search.fts import SearchQueryError, search_fts

    try:
        return search_fts(
            vault.db,
            query,
            filters=filters,
            limit=limit,
            offset=offset,
            ranking=ranking,
            quality_ranked=ranked,
        )
    except SearchQueryError as e:
        if json_output:
            output(error(str(e), "BAD_QUERY"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(2) from e


def _semantic_hits(vault, query: str, limit: int, json_output: bool) -> list:
    from hyperresearch.core.embed import EmbeddingError, semantic_search

    try:
        return semantic_search(vault, query, limit=limit)
    except EmbeddingError as e:
        if json_output:
            output(error(str(e), "EMBEDDINGS_DISABLED"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _refetch_semantic_row(vault, by_id: dict, note_id: str):
    """FTS row for a semantic-only hit, or None when the note is gone."""
    r = by_id.get(note_id)
    if r is not None:
        return r
    row = vault.db.execute(
        "SELECT id, title, path, status, type, tier, content_type, "
        "quality_score, created, updated, word_count, summary "
        "FROM notes WHERE id = ?",
        (note_id,),
    ).fetchone()
    if row is None:
        return None
    r = dict(row)
    r["tags"] = []
    r["snippet"] = ""
    return r


def _blend_semantic(vault, query: str, results: list, limit: int, json_output: bool) -> list:
    """RRF-fuse the FTS ranking with embedding neighbors."""
    from hyperresearch.core.embed import reciprocal_rank_fusion

    sem_hits = _semantic_hits(vault, query, limit, json_output)
    fused = reciprocal_rank_fusion([[r["id"] for r in results], [h["id"] for h in sem_hits]])
    by_id = {r["id"]: r for r in results}
    merged = []
    for note_id, fused_score in fused[:limit]:
        r = _refetch_semantic_row(vault, by_id, note_id)
        if r is None:
            continue
        r["score"] = fused_score
        merged.append(r)
    return merged


def _attach_bodies(vault, results: list, want_body: bool) -> None:
    if not (want_body and results):
        return
    for r in results:
        row = vault.db.execute(
            "SELECT c.body, n.source FROM note_content c "
            "JOIN notes n ON n.id = c.note_id WHERE c.note_id = ?",
            (r["id"],),
        ).fetchone()
        r["body"] = row["body"] if row else ""
        r["source"] = row["source"] if row else None


def _truncate_body(r: dict, remaining: int) -> bool:
    """Truncate one result body to the remaining budget. Returns True when done."""
    body = r.get("body", "")
    if body and len(body) > remaining:
        r["body"] = body[:remaining] + "\n... [truncated]"
        r["truncated"] = True
        return True
    return False


def _apply_token_budget(results: list, max_tokens, chars_per_token: int) -> list:
    """Truncate results to fit within the token limit."""
    if not (max_tokens and results):
        return results
    budget_chars = max_tokens * chars_per_token
    used = 0
    trimmed = []
    for r in results:
        overhead = 200 + len(r.get("title", "")) + len(r.get("id", ""))
        remaining = budget_chars - used - overhead
        if remaining <= 0:
            break
        trimmed.append(r)
        if _truncate_body(r, remaining):
            break
        used += overhead + len(r.get("body", ""))
    return trimmed


def _wrap_untrusted(results: list, want_body: bool) -> None:
    # Wrap fetched bodies as untrusted data — same policy as `note show`.
    # Runs AFTER token-budget truncation so the closing fence can never be
    # severed by the cut.
    if not (want_body and results):
        return
    from hyperresearch.core.untrusted import is_untrusted, wrap_body

    for r in results:
        if r.get("body") and is_untrusted(r.get("source"), r.get("type")):
            r["body"] = wrap_body(r["body"], r["source"])
            r["untrusted"] = True


def _print_search_results(results: list, snippet_len: int) -> None:
    for r in results:
        tags_str = ", ".join(r.get("tags", []))
        console.print(
            f"  [cyan]{r['id']}[/] [bold]{r['title']}[/] "
            f"[dim]({r['status']})[/] [green]{tags_str}[/]"
        )
        if r.get("snippet"):
            console.print(f"    [dim]{r['snippet'][:snippet_len]}[/]")
        console.print()


def _report_search(query: str, vault, results: list, json_output: bool) -> None:
    if json_output:
        output(
            success(
                {"query": query, "results": results, "total": len(results)},
                count=len(results),
                vault=str(vault.root),
            ),
            json_mode=True,
        )
        return
    if not results:
        console.print("[dim]No results found.[/]")
        return
    _print_search_results(results, vault.config.search_snippet_len)


def search(
    query: str = typer.Argument(..., help="Search query"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Filter by tag (AND logic)"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    note_type: str | None = typer.Option(None, "--type", help="Filter by type"),
    tier: str | None = typer.Option(
        None,
        "--tier",
        help="Filter by epistemic tier: ground_truth|institutional|practitioner|commentary|unknown",
    ),
    content_type: str | None = typer.Option(
        None,
        "--content-type",
        help="Filter by artifact kind: paper|docs|article|blog|forum|dataset|policy|code|book|transcript|review|unknown",
    ),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent topic"),
    after: str | None = typer.Option(None, "--after", help="Created after date (YYYY-MM-DD)"),
    before: str | None = typer.Option(None, "--before", help="Created before date (YYYY-MM-DD)"),
    path_glob: str | None = typer.Option(None, "--path", help="Glob filter on path"),
    min_words: int | None = typer.Option(None, "--min-words", help="Minimum word count"),
    max_words: int | None = typer.Option(None, "--max-words", help="Maximum word count"),
    linked_from: str | None = typer.Option(
        None, "--linked-from", help="Only notes linked FROM this note ID"
    ),
    linked_to: str | None = typer.Option(
        None, "--linked-to", help="Only notes that link TO this note ID"
    ),
    min_inbound: int | None = typer.Option(
        None, "--min-inbound", help="Minimum inbound link count"
    ),
    has_backlinks: bool = typer.Option(False, "--has-backlinks", help="Only notes with backlinks"),
    include_body: bool = typer.Option(
        False, "--include-body", help="Include full note body (auto-enabled with --json)"
    ),
    no_body: bool = typer.Option(
        False, "--no-body", help="Disable auto body inclusion in JSON mode"
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-l", help="Max results (default from [search] config)"
    ),
    ranked: bool = typer.Option(
        False,
        "--ranked",
        help="Fold composite source-quality scores into ranking (tier + utility + authority + centrality)",
    ),
    semantic: bool = typer.Option(
        False, "--semantic", help="Blend in embedding similarity (requires [embeddings] provider)"
    ),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination"),
    max_tokens: int | None = typer.Option(
        None, "--max-tokens", help="Truncate results to fit token budget (1 token ~ 4 chars)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Full-text search across all notes."""
    from hyperresearch.models.note import ContentType, Tier
    from hyperresearch.search.filters import SearchFilters

    _validate_search_enum(tier, Tier, "--tier", "INVALID_TIER", json_output)
    _validate_search_enum(
        content_type, ContentType, "--content-type", "INVALID_CONTENT_TYPE", json_output
    )

    vault = _open_search_vault(json_output)
    if limit is None:
        limit = vault.config.search_default_limit

    filters = SearchFilters(
        tags=tag or None,
        status=status,
        note_type=note_type,
        tier=tier,
        content_type=content_type,
        parent=parent,
        after=after,
        before=before,
        path_glob=path_glob,
        min_words=min_words,
        max_words=max_words,
        linked_from=linked_from,
        linked_to=linked_to,
        min_inbound=min_inbound,
        has_backlinks=has_backlinks or None,
    )

    ranking = {
        "title_weight": vault.config.search_title_weight,
        "body_weight": vault.config.search_body_weight,
        "tags_weight": vault.config.search_tags_weight,
        "aliases_weight": vault.config.search_aliases_weight,
        "boost_evergreen": vault.config.search_boost_evergreen,
        "penalize_deprecated": vault.config.search_penalize_deprecated,
        "penalize_stale": vault.config.search_penalize_stale,
    }
    results = _run_fts(vault, query, filters, limit, offset, ranking, ranked, json_output)

    # Hybrid semantic blend: RRF-fuse the FTS ranking with embedding cosine
    # neighbors, then refetch metadata for any semantic-only hits.
    if semantic:
        results = _blend_semantic(vault, query, results, limit, json_output)

    # Auto-include body in JSON mode (agents almost always need it)
    want_body = include_body or (json_output and not no_body)
    _attach_bodies(vault, results, want_body)

    # Token budget: truncate results to fit within limit
    results = _apply_token_budget(results, max_tokens, vault.config.search_chars_per_token)

    # Wrap fetched bodies as untrusted data — same policy as `note show`.
    _wrap_untrusted(results, want_body)

    _report_search(query, vault, results, json_output)
