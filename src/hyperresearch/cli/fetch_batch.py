"""Batch fetch — fetch multiple URLs in one command with batched sync."""

from __future__ import annotations

import hashlib
import sys
from urllib.parse import urlparse

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.core.fetcher import existing_live_note_for_url, reclaim_orphaned_source_row
from hyperresearch.models.output import error, success


def _collect_batch_urls(urls, stdin: bool) -> list:
    """Collect URLs from args and/or stdin."""
    all_urls = list(urls or [])
    if stdin:
        for line in sys.stdin:
            line = line.strip()
            if line and line.startswith("http"):
                all_urls.append(line)
    return all_urls


def _fail_no_input(json_output: bool) -> None:
    if json_output:
        output(error("No URLs provided", "NO_INPUT"), json_mode=True)
    else:
        console.print("[red]No URLs provided.[/] Pass URLs as arguments or use --stdin.")
    raise typer.Exit(1)


def _open_batch_vault(json_output: bool):
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _needs_visible_url(vault, fetch_url: str) -> bool:
    if not vault.config.web_profile:
        return False
    domain = urlparse(fetch_url).netloc.lower()
    return any(d in domain for d in vault.config.fetch.visible_browser_domains)


def _filter_new_urls(conn, all_urls: list, json_output: bool) -> list:
    """Drop already-fetched URLs (orphaned rows don't count as duplicates)."""
    new_urls = []
    for url in all_urls:
        existing = existing_live_note_for_url(conn, url)
        if existing:
            if not json_output:
                console.print(f"  [dim]Skip:[/] {url} (already fetched as {existing['note_id']})")
        else:
            new_urls.append(url)
    return new_urls


def _report_all_fetched(all_urls: list, vault, json_output: bool) -> None:
    if json_output:
        output(
            success({"notes_created": [], "skipped": len(all_urls)}, vault=str(vault.root)),
            json_mode=True,
        )
    else:
        console.print("[dim]All URLs already fetched.[/]")


def _split_by_visibility(vault, new_urls: list) -> tuple:
    """Split URLs into normal (headless batch) and auth-aggressive (visible, sequential)."""
    normal_urls = [u for u in new_urls if not _needs_visible_url(vault, u)]
    visible_urls = [u for u in new_urls if _needs_visible_url(vault, u)]
    return normal_urls, visible_urls


def _fetch_one_result(
    provider, url: str, kind: str, results: list, failed_urls: list, json_output: bool
) -> None:
    try:
        results.append(provider.fetch(url))
    except Exception as exc:
        failed_urls.append({"url": url, "error": str(exc), "phase": kind})
        if not json_output:
            console.print(f"  [red]Failed ({kind}):[/] {url} — {exc}")


def _fetch_normal_urls(
    prov, normal_urls: list, results: list, failed_urls: list, json_output: bool
) -> None:
    """Batch fetch normal URLs, falling back to per-URL on wave failure."""
    if not normal_urls:
        return
    if hasattr(prov, "fetch_many"):
        try:
            results.extend(prov.fetch_many(normal_urls))  # type: ignore[attr-defined]
            return
        except Exception as e:
            # fetch_many can return zero results on a single bad URL
            # inside the batch comprehension. Fall back to per-URL so we
            # don't silently lose the entire wave.
            if not json_output:
                console.print(f"[red]Batch fetch failed:[/] {e}. Falling back to per-URL fetches.")
            for url in normal_urls:
                _fetch_one_result(prov, url, "batch-fallback", results, failed_urls, json_output)
    else:
        for url in normal_urls:
            _fetch_one_result(prov, url, "normal", results, failed_urls, json_output)


def _fetch_visible_urls(
    vault, provider_name, visible_urls: list, results: list, failed_urls: list, json_output: bool
) -> None:
    """Fetch auth-aggressive URLs with a visible browser (sequential)."""
    from hyperresearch.web.base import get_provider

    if not visible_urls:
        return
    visible_prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
        headless=False,
        settings=vault.config.fetch,
        gates=vault.config.junk,
    )
    for url in visible_urls:
        _fetch_one_result(visible_prov, url, "visible", results, failed_urls, json_output)


def _partition_results(results: list, failed_urls: list, vault) -> tuple:
    """Split fetch outcomes into writable pendings and blocked-for-rescue."""
    pending = []  # (url, result, oa_location, rescue_reason)
    blocked = [(f["url"], f"fetch failed: {f['error']}", None) for f in failed_urls]
    for result in results:
        url = result.url
        if result.looks_like_login_wall(url, vault.config.junk):
            blocked.append((url, f"login wall: {result.title}", result.raw_html))
            continue
        pending.append((url, result, None, None))
    return pending, blocked


def _rescue_one_blocked(vault, prov, burl: str, reason: str, raw_html, json_output: bool):
    """Rescue one blocked URL. Returns ((burl, rescued, loc, reason) | None, rescued_flag)."""
    from hyperresearch.core.oa import rescue_full_text
    from hyperresearch.core.scholar import extract_doi

    # URL and meta tags only — a wall page's body carries no DOI worth trusting.
    rescued, loc = rescue_full_text(vault, prov, burl, extract_doi(burl, raw_html, None))
    if rescued is None:
        if raw_html is not None and not json_output:
            console.print(
                f"  [yellow]Auth required:[/] {burl} — login page detected, skipping. "
                "Run 'hyperresearch setup' to create a login profile."
            )
        return None, False
    if not json_output:
        console.print(
            f"  [cyan]Blocked — recovered an open-access copy:[/] {burl} (via {loc.resolver if loc is not None else 'unknown'})"
        )
    return (burl, rescued, loc, reason), True


def _rescue_blocked(vault, prov, blocked: list, json_output: bool) -> tuple:
    """OA-rescue every blocked URL. Returns (rescued_entries, rescued_urls)."""
    rescued_entries = []
    rescued_urls: set[str] = set()
    for burl, reason, raw_html in blocked:
        entry, ok = _rescue_one_blocked(vault, prov, burl, reason, raw_html, json_output)
        if not ok:
            continue
        rescued_entries.append(entry)  # type: ignore[arg-type]
        rescued_urls.add(burl)
    return rescued_entries, rescued_urls


def _prepare_batch_item(vault, prov, url: str, result, oa_location, rescue_reason):
    """DOI recovery + OA substitution for one item. Returns (result, loc, doi, domain, chars)."""
    from hyperresearch.core.oa import recover_full_text
    from hyperresearch.core.scholar import extract_doi

    if oa_location is None:
        detected_doi = extract_doi(url, result.raw_html, result.content)
        original_domain = result.domain
        original_chars = len(result.content or "")
        result, oa_location = recover_full_text(vault, prov, url, detected_doi, result)
    else:
        # Rescued: nothing was read from the source, so its domain comes
        # from the URL and there is no original length to report.
        detected_doi = extract_doi(url, None, None)
        original_domain = urlparse(url).netloc.lower()
        original_chars = 0
    return result, oa_location, detected_doi, original_domain, original_chars


def _write_batch_item(
    vault,
    conn,
    url: str,
    result,
    prov_name: str,
    tags: list,
    parent,
    detected_doi,
    original_domain: str,
    oa_location,
    rescue_reason,
    original_chars: int,
):
    """Write one note file + enrich. Returns (note_path, content_hash, title, domain)."""
    from hyperresearch.core.enrich import enrich_note_file
    from hyperresearch.core.note import write_note
    from hyperresearch.core.oa import oa_frontmatter, recovery_notice

    title = result.title or urlparse(url).path.split("/")[-1] or "Untitled"
    extra_meta = {
        "source": url,
        "source_domain": original_domain,
        "fetched_at": result.fetched_at.isoformat(),
        "fetch_provider": prov_name,
    }
    if detected_doi:
        extra_meta["doi"] = detected_doi
    body_content = result.content
    if oa_location is not None:
        extra_meta.update(
            oa_frontmatter(oa_location, kind="rescued" if rescue_reason else "substituted")
        )
        body_content = (
            recovery_notice(oa_location, url, original_chars, blocked_reason=rescue_reason)
            + "\n"
            + body_content
        )
    note_path = write_note(
        vault.notes_dir,
        title=title,
        body=body_content,
        tags=tags,
        status="draft",
        source=url,
        parent=parent,
        extra_frontmatter=extra_meta,
        run_tag=tags[0] if tags else None,
    )
    # Auto-enrich before sync
    enrich_note_file(note_path, conn, tags)
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
    return note_path, content_hash, title, original_domain


def _print_batch_item(title: str, oa_location, rescue_reason, json_output: bool) -> None:
    if json_output:
        return
    console.print(f"  [green]+[/] {title}")
    if oa_location is not None:
        console.print(
            f"    [cyan]body from:[/] {oa_location.url} "
            f"({oa_location.version or 'version unknown'}, via {oa_location.resolver})"
        )
        if rescue_reason:
            console.print(
                f"    [yellow]source never read[/] ({rescue_reason}) — "
                "title and authors are the open-access copy's too"
            )


def _write_batch_notes(
    vault, conn, prov, pending: list, tags: list, parent, json_output: bool
) -> list:
    """Phase 1: write all note files to disk (no sync yet). Returns note_files."""
    note_files = []
    for url, result, oa_location, rescue_reason in pending:
        result, oa_location, detected_doi, original_domain, original_chars = _prepare_batch_item(
            vault, prov, url, result, oa_location, rescue_reason
        )
        note_path, content_hash, title, domain = _write_batch_item(
            vault,
            conn,
            url,
            result,
            prov.name,
            tags,
            parent,
            detected_doi,
            original_domain,
            oa_location,
            rescue_reason,
            original_chars,
        )
        note_files.append(
            (note_path, url, result, domain, content_hash, oa_location, rescue_reason)
        )
        _print_batch_item(title, oa_location, rescue_reason, json_output)
    return note_files


def _sync_batch_if_needed(vault) -> None:
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)


def _batch_entry(note_id: str, url: str, result, domain: str, oa_location, rescue_reason) -> dict:
    entry = {
        "note_id": note_id,
        "title": result.title or "Untitled",
        "url": url,
        "domain": domain,
        "word_count": len(result.content.split()),
    }
    if oa_location is not None:
        entry["oa"] = {
            "url": oa_location.url,
            "resolver": oa_location.resolver,
            "version": oa_location.version,
            "license": oa_location.license,
            "kind": "rescued" if rescue_reason else "substituted",
            "nothing_from_source": bool(rescue_reason),
            "blocked_reason": rescue_reason,
        }
    return entry


def _insert_batch_sources(conn, vault, prov_name: str, note_files: list, save_assets: bool) -> list:
    """Phase 3: bulk-insert source records (+ assets). Returns created_notes."""
    created_notes = []
    for note_path, url, result, domain, content_hash, oa_location, rescue_reason in note_files:
        note_id = note_path.stem
        conn.execute(
            """INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (url, note_id, domain, result.fetched_at.isoformat(), prov_name, content_hash),
        )
        # The INSERT is also a no-op on an orphaned row (note deleted); claim it
        reclaim_orphaned_source_row(
            conn, url, note_id, domain, result.fetched_at.isoformat(), prov_name, content_hash
        )
        # Save assets if requested
        if save_assets:
            from hyperresearch.cli.fetch import _save_assets as _save_assets_fn

            assets_dir = vault.research_dir / "assets" / note_id
            _save_assets_fn(
                conn,
                result,
                note_id,
                assets_dir,
                settings=vault.config.assets,
                image_timeout_s=vault.config.fetch.image_timeout_s,
            )
        created_notes.append(_batch_entry(note_id, url, result, domain, oa_location, rescue_reason))
    conn.commit()
    return created_notes


def _autolink_batch(vault, created_notes: list) -> None:
    """Phase 4: auto-link across all new notes."""
    if not created_notes:
        return
    from hyperresearch.core.linker import auto_link

    note_ids = [n["note_id"] for n in created_notes]
    if auto_link(vault, note_ids):
        _sync_batch_if_needed(vault)


def _summarize_batch(created_notes: list) -> tuple:
    oa_recovered = sum(1 for n in created_notes if "oa" in n)
    oa_rescued = sum(1 for n in created_notes if n.get("oa", {}).get("kind") == "rescued")
    return oa_recovered, oa_rescued


def _report_batch_done(
    all_urls: list,
    new_urls: list,
    created_notes: list,
    failed_urls: list,
    vault_root,
    json_output: bool,
) -> None:
    oa_recovered, oa_rescued = _summarize_batch(created_notes)
    data = {
        "notes_created": created_notes,
        "total_fetched": len(created_notes),
        "skipped": len(all_urls) - len(new_urls),
        "failed_urls": failed_urls,
        "oa_recovered": oa_recovered,
        "oa_rescued": oa_rescued,
    }
    if json_output:
        output(success(data, count=len(created_notes), vault=str(vault_root)), json_mode=True)
        return
    msg = (
        f"\n[bold]Done:[/] {len(created_notes)} notes created, "
        f"{len(all_urls) - len(new_urls)} skipped (already fetched)"
    )
    if failed_urls:
        msg += f", [red]{len(failed_urls)} failed[/]"
    if oa_recovered:
        msg += (
            f"\n[cyan]{oa_recovered} note(s) carry an open-access full text in place of a "
            "paywalled page[/] — each one says so in its body banner and oa_* frontmatter."
        )
    if oa_rescued:
        msg += (
            f"\n[yellow]{oa_rescued} of those had a source that could not be read at all[/] "
            "— those notes are entirely the open-access copy, titles and authors included."
        )
    console.print(msg + ".")


def fetch_batch(
    urls: list[str] = typer.Argument(None, help="URLs to fetch"),
    stdin: bool = typer.Option(False, "--stdin", help="Read URLs from stdin (one per line)"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags for all notes"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    save_assets: bool = typer.Option(
        False, "--save-assets", "-a", help="Download images and screenshots"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Fetch multiple URLs and save each as a research note. Batched sync for speed."""
    from hyperresearch.web.base import get_provider

    all_urls = _collect_batch_urls(urls, stdin)
    if not all_urls:
        _fail_no_input(json_output)

    vault = _open_batch_vault(json_output)
    vault.auto_sync()
    conn = vault.db

    prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
        settings=vault.config.fetch,
        gates=vault.config.junk,
    )

    # Filter out already-fetched URLs: an orphaned row (note deleted) is not
    # a duplicate; only a live note skips.
    new_urls = _filter_new_urls(conn, all_urls, json_output)
    if not new_urls:
        _report_all_fetched(all_urls, vault, json_output)
        return

    if not json_output:
        console.print(f"[bold]Fetching {len(new_urls)} URLs with {prov.name}...[/]")

    # Split URLs into normal (headless batch) and auth-aggressive (visible, sequential)
    normal_urls, visible_urls = _split_by_visibility(vault, new_urls)

    results = []
    failed_urls: list[dict] = []  # surfaced in JSON output so callers see what was lost
    _fetch_normal_urls(prov, normal_urls, results, failed_urls, json_output)
    _fetch_visible_urls(vault, provider_name, visible_urls, results, failed_urls, json_output)

    # Partition into what can be written and what was blocked. Blocked sources
    # get one open-access rescue attempt before being written off — see
    # cli/fetch.py for the reasoning. It matters more here: the pipeline fetches
    # in waves through this command, so one bot-walled publisher silently drops
    # a whole cluster of papers at once.
    pending, blocked = _partition_results(results, failed_urls, vault)
    rescued_entries, rescued_urls = _rescue_blocked(vault, prov, blocked, json_output)
    pending.extend(rescued_entries)

    # A rescued URL is no longer lost, so it should not still be reported as a
    # failure to the caller.
    failed_urls[:] = [f for f in failed_urls if f["url"] not in rescued_urls]

    # Phase 1: Write all note files to disk (no sync yet). Open-access
    # recovery writes its own notes rather than going through cli.fetch,
    # so the DOI capture and the OA swap are both repeated here.
    note_files = _write_batch_notes(vault, conn, prov, pending, tags, parent, json_output)

    # Phase 2: ONE sync to index all notes
    _sync_batch_if_needed(vault)

    # Phase 3: Bulk-insert source records
    created_notes = _insert_batch_sources(conn, vault, prov.name, note_files, save_assets)

    # Phase 4: Auto-link across all new notes
    _autolink_batch(vault, created_notes)

    _report_batch_done(all_urls, new_urls, created_notes, failed_urls, vault.root, json_output)
