"""Core fetch logic — reusable by CLI and MCP server."""

from __future__ import annotations

import hashlib
import sqlite3
from urllib.parse import urlparse


def existing_live_note_for_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    """Return the ``sources`` row for ``url`` only if it still points at a live note.

    ``sources.note_id`` is ``ON DELETE SET NULL``, so deleting a note leaves its
    row behind with ``note_id = NULL``. That orphan is not a duplicate — the url
    may be fetched again — so this returns None both when the row is absent and
    when it is orphaned. Every duplicate-url check must go through here rather
    than testing row truthiness.
    """
    row = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    if row is None or row["note_id"] is None:
        return None
    return row


def reclaim_orphaned_source_row(
    conn: sqlite3.Connection,
    url: str,
    note_id: str,
    domain: str,
    fetched_at: str,
    provider: str,
    content_hash: str,
) -> None:
    """Point an orphaned ``sources`` row (``note_id IS NULL``) for ``url`` at ``note_id``.

    The CLI fetch paths record a source with ``INSERT OR IGNORE`` so that a
    duplicate-url race is a silent no-op instead of an IntegrityError. An
    orphaned row makes that INSERT a no-op too, which would leave the freshly
    written note with no source record (and, in ``fetch``, trip the race
    detector into deleting it). Call this right after the INSERT: the
    ``note_id IS NULL`` guard means it claims only an orphan and stays a no-op
    when another fetch already owns the row, so the race semantics are unchanged.
    """
    conn.execute(
        """UPDATE sources
           SET note_id = ?, domain = ?, fetched_at = ?, provider = ?,
               content_hash = ?, status = 'active'
           WHERE url = ? AND note_id IS NULL""",
        (note_id, domain, fetched_at, provider, content_hash, url),
    )


def _ensure_new_url(conn, url: str) -> None:
    # An orphaned row (note deleted) is not a duplicate
    existing = existing_live_note_for_url(conn, url)
    if existing:
        raise ValueError(f"URL already fetched as note '{existing['note_id']}'")


def _auto_visible(url: str, visible: bool, vault) -> bool:
    """Auto-visible for sites that kill headless sessions on first contact."""
    if visible or not vault.config.web_profile:
        return visible
    domain = urlparse(url).netloc.lower()
    if any(d in domain for d in vault.config.fetch.visible_browser_domains):
        return True
    return visible


def _reject_login_wall(vault, url: str, result, tags: list) -> None:
    from hyperresearch.core.escalation import maybe_enqueue_blocked_fetch

    item_id = maybe_enqueue_blocked_fetch(
        vault,
        url,
        "login_wall",
        vault_tag=tags[0] if tags else None,
        detail=f"login wall: {result.title}",
    )
    escalated = f" Queued for browser-lane escalation (#{item_id})." if item_id else ""
    raise RuntimeError(
        f"Redirected to login page ({result.title}). "
        "Your browser profile session may have expired. "
        f"Run 'hyperresearch setup' and create a new login profile.{escalated}"
    )


def _reject_junk(vault, url: str, result, tags: list) -> None:
    from hyperresearch.core.escalation import maybe_enqueue_blocked_fetch

    junk_reason = result.looks_like_junk(vault.config.junk)
    if not junk_reason:
        return
    escalated = ""
    if junk_reason.startswith("Bot detection"):
        reason = "captcha" if "captcha" in junk_reason.lower() else "bot_block"
        item_id = maybe_enqueue_blocked_fetch(
            vault,
            url,
            reason,
            vault_tag=tags[0] if tags else None,
            detail=junk_reason,
        )
        if item_id:
            escalated = f" Queued for browser-lane escalation (#{item_id})."
    raise RuntimeError(f"Skipped junk content: {junk_reason}.{escalated}")


def _write_fetched_note(
    vault, url: str, title, result, domain: str, prov_name: str, tags: list, parent
):
    """Write the note file. Returns (note_path, note_title)."""
    from hyperresearch.core.note import write_note
    from hyperresearch.core.scholar import extract_doi

    note_title = title or result.title or urlparse(url).path.split("/")[-1] or "Untitled"
    extra_meta = {
        "source": url,
        "source_domain": domain,
        "fetched_at": result.fetched_at.isoformat(),
        "fetch_provider": prov_name,
    }
    if result.metadata.get("author"):
        extra_meta["author"] = result.metadata["author"]
    detected_doi = extract_doi(url, result.raw_html, result.content)
    if detected_doi:
        extra_meta["doi"] = detected_doi
    note_path = write_note(
        vault.notes_dir,
        title=note_title,
        body=result.content,
        tags=tags,
        status="draft",
        source=url,
        parent=parent,
        extra_frontmatter=extra_meta,
    )
    return note_path, note_title


def _store_raw_file(vault, result, note_path):
    """Save a raw (PDF, etc.) companion file + frontmatter reference."""
    if not (result.raw_bytes and result.raw_content_type):
        return None
    ext_map = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    ext = ext_map.get(result.raw_content_type, "")
    if not ext:
        return None
    raw_dir = vault.research_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_filename = note_path.stem + ext
    raw_file = raw_dir / raw_filename
    raw_file.write_bytes(result.raw_bytes)
    raw_file_path = f"raw/{raw_filename}"
    # Note: tagging and summarization is the agent's job, not an automatic process.
    # Add raw_file reference to frontmatter AFTER enrich (enrich rewrites frontmatter)
    note_text = note_path.read_text(encoding="utf-8")
    if note_text.startswith("---") and "raw_file:" not in note_text:
        end = note_text.find("---", 3)
        if end != -1:
            note_text = note_text[:end] + f"raw_file: {raw_file_path}\n" + note_text[end:]
            note_path.write_text(note_text, encoding="utf-8")
    return raw_file_path


def _record_source_upsert(
    conn, url: str, note_id: str, domain: str, result, prov_name: str
) -> None:
    # Upsert: an orphaned row for this url may already exist
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
    conn.execute(
        """INSERT INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET
               note_id = excluded.note_id,
               domain = excluded.domain,
               fetched_at = excluded.fetched_at,
               provider = excluded.provider,
               content_hash = excluded.content_hash,
               status = 'active'""",
        (url, note_id, domain, result.fetched_at.isoformat(), prov_name, content_hash),
    )
    conn.commit()


def _save_fetcher_assets(vault, conn, result, note_id: str, save_assets: bool) -> list:
    if not save_assets:
        return []
    from hyperresearch.cli.fetch import _save_assets

    assets_dir = vault.research_dir / "assets" / note_id
    return _save_assets(
        conn,
        result,
        note_id,
        assets_dir,
        settings=vault.config.assets,
        image_timeout_s=vault.config.fetch.image_timeout_s,
        max_image_bytes=vault.config.fetch.max_image_bytes,
        allow_private_hosts=vault.config.fetch.allow_private_hosts,
    )


def fetch_and_save(
    vault,
    url: str,
    tags: list[str] | None = None,
    title: str | None = None,
    parent: str | None = None,
    provider_name: str | None = None,
    save_assets: bool = False,
    visible: bool = False,
) -> dict:
    """Fetch a URL and save as a research note. Returns result dict.

    Raises:
        ValueError: If URL is already fetched.
        RuntimeError: If fetch fails.
    """
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.web.base import get_provider

    tags = tags or []
    conn = vault.db

    _ensure_new_url(conn, url)
    visible = _auto_visible(url, visible, vault)

    # Fetch content
    prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
        headless=not visible,
        settings=vault.config.fetch,
        gates=vault.config.junk,
    )

    result = prov.fetch(url)

    # Detect login redirects — abort, but escalate to the browser lane
    if result.looks_like_login_wall(url, vault.config.junk):
        _reject_login_wall(vault, url, result, tags)

    # Detect junk pages — captcha, error pages, binary garbage, empty content
    _reject_junk(vault, url, result, tags)

    # Write note
    domain = result.domain
    note_path, note_title = _write_fetched_note(
        vault, url, title, result, domain, prov.name, tags, parent
    )

    # Save raw file (PDF, etc.) if present
    raw_file_path = _store_raw_file(vault, result, note_path)

    # Sync
    note_id = note_path.stem
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    _record_source_upsert(conn, url, note_id, domain, result, prov.name)

    # Save assets if requested
    saved_assets = _save_fetcher_assets(vault, conn, result, note_id, save_assets)

    return {
        "note_id": note_id,
        "title": note_title,
        "url": url,
        "domain": domain,
        "provider": prov.name,
        "path": str(note_path.relative_to(vault.root)),
        "word_count": len(result.content.split()),
        "assets": saved_assets,
        "raw_file": raw_file_path,
    }
