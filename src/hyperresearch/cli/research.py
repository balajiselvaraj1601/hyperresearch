"""Research command — deep research: search → fetch → follow links → save → synthesize."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.core.fetcher import existing_live_note_for_url, reclaim_orphaned_source_row
from hyperresearch.models.output import error, success


def _open_research_vault(json_output: bool):
    """Discover the vault or report NO_VAULT and exit 1."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _sync_vault(vault) -> None:
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)


def _web_search(prov, vault, topic: str, max_results: int, json_output: bool) -> list | None:
    """Search or report why not. Returns results, or None when already handled."""
    try:
        search_results = prov.search(topic, max_results=max_results)
    except NotImplementedError:
        if json_output:
            output(
                error(
                    f"Provider '{prov.name}' does not support web search. "
                    "Use your agent's built-in search, then pipe URLs into 'hyperresearch fetch'.",
                    "NO_SEARCH",
                ),
                json_mode=True,
            )
        else:
            console.print(
                f"[red]Provider '{prov.name}' cannot search.[/] "
                "Use your agent's built-in search, then pipe URLs into 'hyperresearch fetch'."
            )
        raise typer.Exit(1)
    if not search_results:
        if json_output:
            output(
                success({"notes_created": [], "topic": topic}, vault=str(vault.root)),
                json_mode=True,
            )
        else:
            console.print("[yellow]No results found.[/]")
        return None
    return search_results


def _fetch_search_results(
    vault, conn, prov, search_results, tags, parent, max_pages: int, json_output: bool
):
    """Step 2: fetch and save each result. Returns (created, fetched_urls, pages)."""
    created_notes: list[dict] = []
    fetched_urls: set[str] = set()
    pages_fetched = 0
    for result in search_results:
        if pages_fetched >= max_pages:
            break
        note_data = _save_result(vault, conn, prov, result, tags, parent)
        if note_data:
            created_notes.append(note_data)
            fetched_urls.add(result.url)
            pages_fetched += 1
            if not json_output:
                console.print(f"  [green]+[/] {note_data['title']}")
    return created_notes, fetched_urls, pages_fetched


def _fetch_follow_link(
    vault, conn, prov, link_url: str, fetched_urls: set, tags, parent, depth: int, json_output: bool
):
    """Fetch one followed link. Returns (note_data, child_links)."""
    # An orphaned row (note deleted) is not a duplicate
    if existing_live_note_for_url(conn, link_url):
        fetched_urls.add(link_url)
        return None, []
    try:
        result = prov.fetch(link_url)
        note_data = _save_result(vault, conn, prov, result, tags, parent)
    except Exception:
        return None, []
    if not note_data:
        return None, []
    if not json_output:
        console.print(f"  [dim]+[/] {note_data['title']} [dim](depth {depth})[/]")
    # Collect links from this page for the next depth
    return note_data, _extract_links_from_results([result])


def _follow_link_wave(
    vault,
    conn,
    prov,
    links_to_follow,
    fetched_urls: set,
    created_notes: list,
    pages_fetched: int,
    max_pages: int,
    tags,
    parent,
    depth_num: int,
    json_output: bool,
):
    """Fetch one wave of followed links. Returns (next_links, pages_fetched)."""
    next_links: list[str] = []
    for link_url in links_to_follow:
        if pages_fetched >= max_pages:
            break
        if link_url in fetched_urls:
            continue
        note_data, child_links = _fetch_follow_link(
            vault, conn, prov, link_url, fetched_urls, tags, parent, depth_num, json_output
        )
        if note_data:
            created_notes.append(note_data)
            fetched_urls.add(link_url)
            pages_fetched += 1
            next_links.extend(child_links)
    return next_links, pages_fetched


def _follow_links(
    vault,
    conn,
    prov,
    search_results,
    created_notes: list,
    fetched_urls: set,
    pages_fetched: int,
    depth: int,
    max_pages: int,
    tags,
    parent,
    json_output: bool,
) -> int:
    """Step 3: follow links to the requested depth. Returns pages_fetched."""
    if depth <= 0 or pages_fetched >= max_pages:
        return pages_fetched
    links_to_follow = _extract_links_from_results(search_results)
    for d in range(depth):
        if pages_fetched >= max_pages:
            break
        next_links, pages_fetched = _follow_link_wave(
            vault,
            conn,
            prov,
            links_to_follow,
            fetched_urls,
            created_notes,
            pages_fetched,
            max_pages,
            tags,
            parent,
            d + 1,
            json_output,
        )
        links_to_follow = [u for u in next_links if u not in fetched_urls]
    return pages_fetched


def _write_synthesis(
    vault, topic: str, created_notes: list, tags, parent, json_output: bool
) -> None:
    """Step 5: generate the synthesis (map-of-content) note."""
    from hyperresearch.core.note import write_note
    from hyperresearch.models.note import slugify

    if not created_notes:
        return
    moc_id = slugify(f"research-{topic}")
    wiki_links = "\n".join(
        f"- [[{n['note_id']}]] — {n.get('summary', n['title'])}" for n in created_notes
    )
    moc_body = (
        f"# Research: {topic}\n\n"
        f"**{len(created_notes)} sources collected** "
        f"on {datetime.now(UTC).strftime('%Y-%m-%d')}.\n\n"
        f"## Sources\n\n{wiki_links}\n"
    )
    moc_tags = list(set([*tags, "research", "moc"]))
    moc_path = write_note(
        vault.notes_dir,
        title=f"Research: {topic}",
        body=moc_body,
        note_id=moc_id,
        tags=moc_tags,
        status="review",
        note_type="moc",
        parent=parent,
        summary=f"Research synthesis: {topic} ({len(created_notes)} sources)",
    )
    # Final sync to pick up the MOC
    _sync_vault(vault)
    created_notes.append(
        {
            "note_id": moc_id,
            "title": f"Research: {topic}",
            "type": "moc",
            "path": str(moc_path.relative_to(vault.root)),
        }
    )
    if not json_output:
        console.print(f"\n[bold green]Synthesis:[/] [[{moc_id}]]")


def _auto_link_notes(vault, created_notes: list, json_output: bool) -> None:
    """Step 6: holistic auto-linking across all new notes."""
    from hyperresearch.core.linker import auto_link

    if not created_notes:
        return
    note_ids = [n["note_id"] for n in created_notes]
    link_report = auto_link(vault, note_ids)
    if not link_report:
        return
    _sync_vault(vault)
    if not json_output:
        total_links = sum(len(v) for v in link_report.values())
        console.print(
            f"[green]Auto-linked:[/] {total_links} connections across {len(link_report)} notes"
        )


def _collect_hubs(conn, created_notes: list) -> list:
    hubs = []
    if not created_notes:
        return hubs
    hub_rows = conn.execute(
        "SELECT target_id, COUNT(*) as cnt FROM links "
        "WHERE target_id IS NOT NULL GROUP BY target_id ORDER BY cnt DESC LIMIT 5"
    ).fetchall()
    for row in hub_rows:
        title_row = conn.execute(
            "SELECT title FROM notes WHERE id = ?", (row["target_id"],)
        ).fetchone()
        if title_row:
            hubs.append(
                {"id": row["target_id"], "title": title_row["title"], "inbound_links": row["cnt"]}
            )
    return hubs


def _surface_hubs(conn, created_notes: list, json_output: bool) -> list:
    """Step 7: surface hub notes. Returns the hub list."""
    hubs = _collect_hubs(conn, created_notes)
    if hubs and not json_output:
        console.print("\n[bold]Hub notes[/] (most connected):")
        for h in hubs:
            console.print(f"  [{h['inbound_links']} links] [[{h['id']}]] {h['title']}")
    return hubs


def _report_research_done(
    topic: str,
    prov_name: str,
    created_notes: list,
    pages_fetched: int,
    depth: int,
    hubs: list,
    vault_root,
    json_output: bool,
) -> None:
    data = {
        "topic": topic,
        "provider": prov_name,
        "notes_created": created_notes,
        "total_fetched": pages_fetched,
        "depth": depth,
        "hubs": hubs,
    }
    if json_output:
        output(success(data, count=len(created_notes), vault=str(vault_root)), json_mode=True)
    else:
        console.print(
            f"\n[bold]Done:[/] {len(created_notes)} notes created. "
            f"Start with: hyperresearch note show {created_notes[-1]['note_id']} -j"
        )


def research(
    topic: str = typer.Argument(..., help="Research topic or question"),
    max_results: int = typer.Option(5, "--max", "-m", help="Max search results to fetch"),
    depth: int = typer.Option(0, "--depth", "-d", help="Link-follow depth (0 = no following)"),
    max_pages: int = typer.Option(10, "--max-pages", help="Max total pages to fetch"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags for all created notes"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Deep research: search the web, fetch results, save as linked notes, generate synthesis."""
    from hyperresearch.web.base import get_provider

    vault = _open_research_vault(json_output)
    vault.auto_sync()
    conn = vault.db
    prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
    )

    # Step 1: Search
    if not json_output:
        console.print(f"[bold]Researching:[/] {topic}")
        console.print(f"[dim]Provider: {prov.name}, max results: {max_results}, depth: {depth}[/]")

    search_results = _web_search(prov, vault, topic, max_results, json_output)
    if search_results is None:
        return
    if not json_output:
        console.print(f"[green]Found {len(search_results)} results[/]")

    # Step 2: Fetch and save each result
    created_notes, fetched_urls, pages_fetched = _fetch_search_results(
        vault, conn, prov, search_results, tags, parent, max_pages, json_output
    )

    # Step 3: Follow links (depth > 0)
    pages_fetched = _follow_links(
        vault,
        conn,
        prov,
        search_results,
        created_notes,
        fetched_urls,
        pages_fetched,
        depth,
        max_pages,
        tags,
        parent,
        json_output,
    )

    # Step 4: Sync to index everything
    _sync_vault(vault)

    # Step 5: Generate synthesis note (map-of-content)
    _write_synthesis(vault, topic, created_notes, tags, parent, json_output)

    # Step 6: Holistic auto-linking across all new notes
    _auto_link_notes(vault, created_notes, json_output)

    # Step 7: Surface hub notes
    hubs = _surface_hubs(conn, created_notes, json_output)

    _report_research_done(
        topic, prov.name, created_notes, pages_fetched, depth, hubs, vault.root, json_output
    )


def _save_result(vault, conn, prov, result, tags, parent) -> dict | None:
    """Save a single WebResult as a note. Returns note data dict or None if skipped."""
    from hyperresearch.core.note import write_note

    url = result.url

    # Skip login redirects
    if result.looks_like_login_wall(url):
        return None

    # Skip if already fetched (an orphaned row — note deleted — is not a duplicate)
    if existing_live_note_for_url(conn, url):
        return None

    title = result.title or urlparse(url).path.split("/")[-1] or "Untitled"
    domain = result.domain
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]

    extra_meta = {
        "source": url,
        "source_domain": domain,
        "fetched_at": result.fetched_at.isoformat(),
        "fetch_provider": prov.name,
    }

    note_path = write_note(
        vault.notes_dir,
        title=title,
        body=result.content,
        tags=tags,
        status="draft",
        source=url,
        parent=parent,
        extra_frontmatter=extra_meta,
    )

    # Auto-enrich: add suggested tags and summary before sync
    from hyperresearch.core.enrich import enrich_note_file

    enrich_note_file(note_path, conn, tags)

    # Sync so the note exists in the notes table (needed for FK on sources)
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    note_id = note_path.stem
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    conn.execute(
        """INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash),
    )
    # The INSERT is also a no-op on an orphaned row (note deleted); claim it
    reclaim_orphaned_source_row(
        conn, url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash
    )
    conn.commit()

    return {
        "note_id": note_id,
        "title": title,
        "url": url,
        "domain": domain,
        "path": str(note_path.relative_to(vault.root)),
        "word_count": len(result.content.split()),
        "summary": result.content[:120].replace("\n", " ").strip(),
    }


def _extract_links_from_results(results) -> list[str]:
    """Extract outbound HTTP links from result content."""
    urls = []
    url_re = re.compile(r'https?://[^\s<>\[\]"\']+')
    for r in results:
        for match in url_re.finditer(r.content):
            url = match.group(0).rstrip(".,;:)")
            # Skip common noise
            parsed = urlparse(url)
            if parsed.netloc and not any(
                skip in parsed.netloc
                for skip in ["google.com", "facebook.com", "twitter.com", "youtube.com"]
            ):
                urls.append(url)
    return list(dict.fromkeys(urls))  # Dedupe, preserve order
