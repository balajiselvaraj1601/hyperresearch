"""Scholar command — academic and specialist source discovery.

`hpr sources score` enriches records the vault already holds. This command
finds them. Every provider behind it shares one cache, one per-host courtesy
rate limiter, and one result shape, so a multi-source search is a single
merged list rather than eight lists a human has to reconcile by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

if TYPE_CHECKING:
    import sqlite3

app = typer.Typer()

_SCOPES = ("all", "papers")


def _open_cache() -> tuple[sqlite3.Connection | None, str | None]:
    """The vault's api_cache connection, or None when run outside a vault.

    Discovery is useful without a vault — a user triaging sources before
    committing to a run should not be forced to init one — so a missing vault
    costs the cache, not the command.
    """
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError:
        return None, None
    return vault.db, str(vault.root)


def _check_scope(scope: str, json_output: bool) -> None:
    if scope in _SCOPES:
        return
    message = f"Unknown scope '{scope}'. Use one of: {', '.join(_SCOPES)}"
    if json_output:
        output(error(message, "BAD_SCOPE"), json_mode=True)
    else:
        console.print(f"[red]Error:[/] {message}")
    raise typer.Exit(1)


def _print_skipped_notes(notes: list) -> None:
    for note in notes:
        console.print(f"  [dim]skipped — {note}[/]")


def _resolve_scholar_providers(sources: list, scope: str, json_output: bool):
    from hyperresearch.scholar import registry

    notes = registry.unavailable_notes(scope)
    providers = registry.get_providers(list(sources) or None, scope=scope)
    if providers:
        return providers, notes
    message = (
        f"No providers available for --source {', '.join(sources)}"
        if sources
        else f"No providers available in scope '{scope}'"
    )
    if json_output:
        output(error(message, "NO_PROVIDERS"), json_mode=True)
    else:
        console.print(f"[red]Error:[/] {message}")
        _print_skipped_notes(notes)
    raise typer.Exit(1)


def _search_one_provider(provider, conn, query: str, limit: int, fresh: bool):
    """Search one provider. Returns (found, failure)."""
    from hyperresearch.scholar.base import ProviderError

    try:
        return provider.search(conn, query, limit, fresh=fresh), None
    except ProviderError as exc:
        return None, {"source": provider.slug, "error": str(exc)}
    except Exception as exc:
        # One broken provider must not cost the user the other seven.
        return None, {"source": provider.slug, "error": f"{type(exc).__name__}: {exc}"}


def _search_all_providers(providers, conn, query: str, limit: int, fresh: bool):
    """Query providers one at a time. Returns (collected, failures, per_source)."""
    collected = []
    failures = []
    per_source: dict[str, int] = {}
    for provider in providers:
        found, failure = _search_one_provider(provider, conn, query, limit, fresh)
        if failure is not None:
            failures.append(failure)
            continue
        per_source[provider.slug] = len(found)
        collected.extend(found)
    return collected, failures, per_source


def _apply_year_floor(merged: list, year_from) -> list:
    if year_from is None:
        return merged
    # Records with no year survive: we drop what we can show is too old,
    # not what we simply cannot date.
    return [p for p in merged if p.year is None or p.year >= year_from]


def _paper_bits(paper) -> list:
    bits = [f"[cyan]{paper.source}[/]"]
    also = paper.extra.get("also_in")
    if also:
        bits.append(f"[dim]also in {also}[/]")
    if paper.venue:
        bits.append(paper.venue)
    if paper.citation_count is not None:
        bits.append(f"{paper.citation_count} citations")
    if paper.doi:
        bits.append(f"doi:{paper.doi}")
    return bits


def _print_paper(paper) -> None:
    year = paper.year or "n.d."
    console.print(f"[bold]{paper.title}[/] [dim]({year})[/]")
    if paper.authors:
        shown = ", ".join(paper.authors[:4])
        more = f" +{len(paper.authors) - 4}" if len(paper.authors) > 4 else ""
        console.print(f"  [dim]{shown}{more}[/]")
    console.print(f"  {' · '.join(_paper_bits(paper))}")
    if paper.pdf_url or paper.url:
        console.print(f"  [dim]{paper.pdf_url or paper.url}[/]")


def _print_search_summary(
    results: list, total_merged: int, collected: list, providers, failures: list, notes: list
) -> None:
    console.print(
        f"\n[dim]{len(results)} shown / {total_merged} merged from "
        f"{len(collected)} records across {len(providers)} provider(s)[/]"
    )
    for failure in failures:
        console.print(f"[yellow]failed:[/] {failure['source']} — {failure['error']}")
    for note in notes:
        console.print(f"[dim]skipped — {note}[/]")


def _report_search_results(
    query: str,
    results: list,
    total_merged: int,
    collected: list,
    providers,
    failures: list,
    notes: list,
    vault_root,
    json_output: bool,
    data: dict,
) -> None:
    if json_output:
        output(success(data, count=len(results), vault=vault_root), json_mode=True)
        return
    if not results:
        console.print(
            f"[dim]No results for[/] '{query}' [dim]across {len(providers)} provider(s).[/]"
        )
    for paper in results:
        _print_paper(paper)
    _print_search_summary(results, total_merged, collected, providers, failures, notes)


def _print_provider_rows(rows: list) -> None:
    for row in rows:
        mark = "[green]ready[/]" if row["available"] else "[yellow]needs key[/]"
        console.print(f"{mark} [cyan]{row['slug']}[/] — {row['label']} [dim]({row['kind']})[/]")
        if row["covers"]:
            console.print(f"  [dim]{row['covers']}[/]")
        if row["reason"]:
            console.print(f"  [yellow]{row['reason']}[/]")
    console.print(f"\n[dim]{len(rows)} provider(s)[/]")


@app.command("search")
def scholar_search(
    query: str = typer.Argument(..., help="Search query"),
    sources: list[str] = typer.Option(
        [], "--source", "-s", help="Provider slug (repeatable; default: every available provider)"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results per provider"),
    scope: str = typer.Option(
        "all", "--scope", help="all | papers (papers excludes trials/filings/series)"
    ),
    year_from: int | None = typer.Option(
        None, "--year-from", help="Drop records published before this year"
    ),
    fresh: bool = typer.Option(False, "--fresh", help="Bypass the API cache and re-query upstream"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Search academic and specialist sources, merged and deduplicated.

    Providers are queried one at a time on purpose: the rate limiter is global
    and per-host, so concurrency buys almost nothing and risks tripping the
    courtesy limits these free APIs run on.
    """
    from hyperresearch.scholar.dedup import merge_papers

    _check_scope(scope, json_output)
    providers, notes = _resolve_scholar_providers(sources, scope, json_output)
    conn, vault_root = _open_cache()

    collected, failures, per_source = _search_all_providers(providers, conn, query, limit, fresh)

    precedence = [p.slug for p in providers]
    # `--limit` is per provider, not a cap on the merged list. Merging sorts
    # by provider precedence, so a post-merge cap would show only the first
    # provider's records at small limits and make every other source look
    # empty — a user asking for DOAB books alongside OpenAlex would see none.
    merged = _apply_year_floor(merge_papers(collected, precedence), year_from)
    total_merged = len(merged)
    results = merged

    data = {
        "query": query,
        "scope": scope,
        "providers": precedence,
        "per_source": per_source,
        "raw_records": len(collected),
        "merged_records": total_merged,
        "returned": len(results),
        "cached": conn is not None and not fresh,
        "failed": failures,
        "unavailable": notes,
        "results": [p.to_dict() for p in results],
    }
    _report_search_results(
        query,
        results,
        total_merged,
        collected,
        providers,
        failures,
        notes,
        vault_root,
        json_output,
        data,
    )


@app.command("sources")
def scholar_sources(
    scope: str = typer.Option("all", "--scope", help="all | papers"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List every discovery provider, what it covers, and whether it can run.

    This is the discoverability surface: picking a source should not require
    reading the provider modules or guessing from a slug.
    """
    from hyperresearch.scholar import registry

    _check_scope(scope, json_output)
    providers = registry.get_providers(scope=scope, include_unavailable=True)
    rows = [
        {
            "slug": p.slug,
            "label": p.label,
            "covers": p.covers,
            "kind": "papers" if p.slug in registry.PAPER_SLUGS else "specialist",
            "needs_key": p.needs_key,
            "available": p.available(),
            "reason": p.unavailable_reason(),
        }
        for p in providers
    ]

    if json_output:
        output(success(rows, count=len(rows)), json_mode=True)
        return

    if not rows:
        console.print("[dim]No discovery providers are installed.[/]")
        return

    _print_provider_rows(rows)
