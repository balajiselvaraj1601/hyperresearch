"""Fetch and websearch commands — save web content as research notes."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import typer

from hyperresearch.cli._output import console, err_console, output
from hyperresearch.core.config import AssetSettings, FetchSettings
from hyperresearch.core.fetcher import existing_live_note_for_url, reclaim_orphaned_source_row
from hyperresearch.models.output import error, success

app = typer.Typer()

# URL patterns that are almost never content images
SKIP_URL_PATTERNS = (
    "logo",
    "icon",
    "favicon",
    "badge",
    "avatar",
    "sprite",
    "banner",
    "ad-",
    "ads/",
    "advert",
    "tracking",
    "pixel",
    "analytics",
    "button",
    "arrow",
    "caret",
    "spinner",
    "loader",
    "gravatar.com",
    "googleusercontent.com/a/",
    "shields.io",
    "github.com/fluidicon",
    "platform-lookaside",
    "syndication",
    "facebook.com",
    "twitter.com/favicon",
    "linkedin.com/li/",
)


def _append_suggested_by_to_existing(
    vault_root: Path,
    note_id: str,
    suggested_by: list[str],
    reason: str | None,
) -> int:
    """Append `*Suggested by [[src]] — reason*` breadcrumb lines to an existing note.

    Idempotent: if a breadcrumb for a given source id already exists anywhere
    in the body, it is not re-added. Returns the number of new breadcrumbs
    actually added.
    """
    # Find the note file — scan output/notes/ for `<note-id>.md` or walk subdirs
    from hyperresearch.core.frontmatter import parse_frontmatter, serialize_frontmatter

    note_path = None
    for candidate in vault_root.rglob(f"{note_id}.md"):
        # Require it to be under a notes directory so we don't match index files
        if "notes" in candidate.parts:
            note_path = candidate
            break
    if note_path is None:
        return 0

    text = note_path.read_text(encoding="utf-8-sig")
    meta, body = parse_frontmatter(text)

    reason_suffix = f" — {reason}" if reason else ""
    added = 0
    new_lines = []
    for src_id in suggested_by:
        src_clean = src_id.strip()
        if not src_clean:
            continue
        # Skip if a breadcrumb for this source id already exists in the body
        existing_marker = f"[[{src_clean}]]"
        if existing_marker in body:
            continue
        new_lines.append(f"*Suggested by [[{src_clean}]]{reason_suffix}*")
        added += 1

    if added == 0:
        return 0

    # Prepend the new breadcrumb lines to the body
    breadcrumb_block = "\n".join(new_lines) + "\n\n"
    new_body = breadcrumb_block + body
    new_text = serialize_frontmatter(meta) + "\n" + new_body
    note_path.write_text(new_text, encoding="utf-8")
    return added


# content_type -> tier, in the priority order the sequential checks used.
# Official documentation IS the ground truth for a product/standard; source
# code, README, and repo metadata are ground truth for a tool. A paper
# defaults to institutional (the agent may upgrade original-data reports or
# downgrade derivatives). Transcripts start at commentary; promote in curation.
_TIER_BY_CONTENT_TYPE = (
    ("policy", "ground_truth"),
    ("dataset", "ground_truth"),
    ("docs", "ground_truth"),
    ("code", "ground_truth"),
    ("paper", "institutional"),
    ("forum", "practitioner"),
    ("review", "practitioner"),
    ("article", "commentary"),
    ("blog", "commentary"),
    ("transcript", "commentary"),
)


def _detect_tier(url: str, content_type: str) -> str:
    """Guess the epistemic tier from URL + content_type. Returns a Tier value.

    This is a coarse first pass. The curation-time agent is expected to refine
    (e.g. a medium.com post could be practitioner if it's by a named engineer,
    or commentary if it's a generic explainer — only reading can tell).

    Defaults prioritize reducing the agent's curation load: URLs with strong
    signal get a non-unknown default so the agent only needs to verify, not
    classify from scratch.
    """
    domain = urlparse(url).netloc.lower()

    # Ground truth: official primary sources — filings, specs, policy text, datasets
    if domain.endswith((".gov", ".gov.uk", ".europa.eu")) or ".gov." in domain:
        return "ground_truth"
    for known_type, tier in _TIER_BY_CONTENT_TYPE:
        if content_type == known_type:
            return tier
    # Institutional: canonical reference works
    if "wikipedia.org" in domain or "britannica.com" in domain:
        return "institutional"

    return "unknown"


# Papers: arxiv, doi, direct PDFs, openreview, ssrn, biorxiv, pubmed
_PAPER_DOMAINS = (
    "arxiv.org",
    "doi.org",
    "openreview.net",
    "ssrn.com",
    "biorxiv.org",
    "medrxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov/pmc",
    "semanticscholar.org",
    "openalex.org",
)

# Code: github, gitlab, bitbucket, pypi
_CODE_DOMAINS = ("github.com", "gitlab.com", "bitbucket.org", "pypi.org", "crates.io", "npmjs.com")

# Docs: common documentation platforms
_DOCS_DOMAINS = ("readthedocs.io", "readthedocs.org", "docs.rs", "developer.mozilla.org")

_DOCS_PATH_MARKERS = ("/docs/", "/documentation/", "/api/reference", "/reference/")

# Community kinds in priority order: (domains, kind)
_COMMUNITY_KINDS = (
    (
        (
            "reddit.com",
            "news.ycombinator.com",
            "stackoverflow.com",
            "stackexchange.com",
            "lobste.rs",
            "lemmy.",
            "discourse.",
        ),
        "forum",
    ),
    (
        (
            "medium.com",
            "substack.com",
            "dev.to",
            "hashnode.com",
            "hashnode.dev",
            "blogspot.com",
            "wordpress.com",
            "ghost.io",
        ),
        "blog",
    ),
    (("youtube.com", "youtu.be", "vimeo.com"), "transcript"),
    (("wikipedia.org", "wikimedia.org", "britannica.com"), "article"),
    (("kaggle.com", "data.gov", "data.world", "zenodo.org", "figshare.com"), "dataset"),
    (
        (
            "nytimes.com",
            "wsj.com",
            "ft.com",
            "bloomberg.com",
            "reuters.com",
            "bbc.com",
            "theatlantic.com",
            "newyorker.com",
            "economist.com",
        ),
        "article",
    ),
)


def _ctype_paper(domain: str, path: str, raw_content_type: str | None) -> str | None:
    if raw_content_type and "pdf" in raw_content_type.lower():
        return "paper"
    if any(d in domain for d in _PAPER_DOMAINS):
        return "paper"
    if path.endswith(".pdf"):
        return "paper"
    return None


def _ctype_code_data_policy(domain: str) -> str | None:
    if any(d in domain for d in _CODE_DOMAINS):
        return "code"
    # Dataset portals that happen to live on .gov domains must win first
    if domain in ("data.gov", "data.gov.uk") or (
        domain.startswith("data.") and domain.endswith((".gov", ".gov.uk", ".europa.eu"))
    ):
        return "dataset"
    # Policy: gov domains, EU, regulator sites
    if (
        domain.endswith((".gov", ".gov.uk", ".europa.eu"))
        or ".gov." in domain
        or "regulations.gov" in domain
    ):
        return "policy"
    return None


def _ctype_docs(domain: str, path: str) -> str | None:
    if any(d in domain for d in _DOCS_DOMAINS):
        return "docs"
    if domain.startswith(("docs.", "documentation.")) or ".readthedocs." in domain:
        return "docs"
    if path.endswith("/docs") or any(s in path for s in _DOCS_PATH_MARKERS):
        return "docs"
    return None


def _ctype_community(domain: str) -> str | None:
    for domains, kind in _COMMUNITY_KINDS:
        if any(d in domain for d in domains):
            return kind
    return None


def _detect_content_type(url: str, raw_content_type: str | None = None) -> str:
    """Guess the artifact kind from URL + MIME. Returns a ContentType value or 'unknown'.

    This is a coarse first pass. The creation-time agent is expected to refine
    during curation if the URL/MIME heuristic is wrong (e.g. a medium.com URL
    could be blog OR article).
    """
    domain = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    kind = _ctype_paper(domain, path, raw_content_type)
    if kind is not None:
        return kind
    kind = _ctype_code_data_policy(domain)
    if kind is not None:
        return kind
    kind = _ctype_docs(domain, path)
    if kind is not None:
        return kind
    return _ctype_community(domain) or "unknown"


def _credit_run_spend(vault, tags: list[str]) -> None:
    """Count this fetch on the manifest of any live run named in `--tag`.

    Fetchers tag every note with the vault_tag, so the run's
    `spend.sources_fetched` / `notes_written` can be kept by the CLI instead
    of relying on the orchestrator to call `run spend` (nobody did: both
    2026-09-18 runs shipped with `sources_fetched: 0`). Best-effort; a
    manifest problem never fails the fetch.
    """
    from hyperresearch.core.runs import MANIFEST_NAME, RunError, add_spend

    for tag in tags:
        if not (vault.run_dir(tag) / MANIFEST_NAME).exists():
            continue
        try:
            add_spend(vault, tag, sources_fetched=1, notes_written=1)
        except (RunError, OSError):
            pass


def _open_fetch_vault(json_output: bool):
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


def _handle_duplicate_note(
    vault, conn, url: str, suggested_by: list, suggested_by_reason, json_output: bool
) -> bool:
    """Duplicate-URL path. Returns True when handled, False when not a duplicate."""
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    existing = existing_live_note_for_url(conn, url)
    if not existing:
        return False
    note_id = existing["note_id"]
    if not suggested_by:
        if json_output:
            output(
                error(f"URL already fetched as note '{note_id}'", "DUPLICATE_URL"),
                json_mode=True,
            )
        else:
            console.print(f"[yellow]Already fetched:[/] {url} → note '{note_id}'")
        raise typer.Exit(1)
    added = _append_suggested_by_to_existing(vault.root, note_id, suggested_by, suggested_by_reason)
    plan = compute_sync_plan(vault)
    if plan.to_update:
        execute_sync(vault, plan)
    data = {
        "note_id": note_id,
        "url": url,
        "duplicate": True,
        "backlinks_added": added,
        "message": (
            f"URL already fetched; added {added} backlink(s) to existing note"
            if added
            else "URL already fetched; breadcrumb(s) already present"
        ),
    }
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[yellow]Already fetched:[/] {url} → note '{note_id}'")
        console.print(f"  added {added} backlink(s) to existing note")
    return True


def _maybe_auto_visible(url: str, visible: bool, vault) -> bool:
    """Auto-visible for sites that kill headless sessions on first contact."""
    if visible or not vault.config.web_profile:
        return visible
    domain = urlparse(url).netloc.lower()
    if any(d in domain for d in vault.config.fetch.visible_browser_domains):
        return True
    return visible


def _attempt_rescue(vault, prov, url: str, reason: str, raw_html, json_output: bool):
    """Attempt an OA rescue. Returns (rescued, reason, loc, doi) or all-Nones."""
    from hyperresearch.core.oa import rescue_full_text
    from hyperresearch.core.scholar import extract_doi

    # URL and meta tags only — never the blocked page's body text, which on
    # a captcha or error page carries no DOI worth trusting.
    doi = extract_doi(url, raw_html, None)
    rescued, loc = rescue_full_text(vault, prov, url, doi)
    if rescued is None:
        return None, None, None, None
    if not json_output:
        resolver = loc.resolver if loc is not None else "unknown"
        console.print(
            f"[cyan]Source blocked — recovered an open-access copy[/] "
            f"({resolver}, {len(rescued.content or ''):,} chars)"
        )
    return rescued, reason, loc, doi


def _fetch_initial_result(prov, vault, url: str, json_output: bool):
    """Fetch, rescuing fetch failures. Returns (result, reason, loc, doi)."""
    try:
        return prov.fetch(url), None, None, None
    except Exception as e:
        rescued, reason, loc, doi = _attempt_rescue(
            vault, prov, url, f"fetch failed: {e}", None, json_output
        )
        if rescued is None:
            if json_output:
                output(error(str(e), "FETCH_ERROR"), json_mode=True)
            else:
                console.print(f"[red]Fetch failed:[/] {e}")
            raise typer.Exit(1)
        return rescued, reason, loc, doi


def _abort_blocked(
    msg: str, escalated_code: str, plain_code: str, item_id, json_output: bool, prefix: str
) -> None:
    if json_output:
        output(error(msg, escalated_code if item_id else plain_code), json_mode=True)
    else:
        console.print(f"{prefix}{msg}")
    raise typer.Exit(1)


def _handle_login_wall(
    vault,
    prov,
    url: str,
    result,
    rescue: tuple,
    tags: list,
    suggested_by: list,
    utility_score,
    json_output: bool,
):
    """Login-wall path. Returns (result, reason, loc, doi)."""
    rescue_reason, oa_location, rescue_doi = rescue
    if oa_location is not None or not result.looks_like_login_wall(url, vault.config.junk):
        return result, rescue_reason, oa_location, rescue_doi
    rescued, reason, loc, doi = _attempt_rescue(
        vault, prov, url, f"login wall: {result.title}", result.raw_html, json_output
    )
    if rescued is not None:
        return rescued, reason, loc, doi
    item_id = _escalate_blocked(
        vault,
        url,
        "login_wall",
        tags,
        suggested_by,
        utility_score,
        detail=f"login wall: {result.title}",
    )
    escalated = f" Queued for browser-lane escalation (#{item_id})." if item_id else ""
    msg = (
        f"Redirected to login page ({result.title}). "
        "Try --visible flag (runs browser non-headless, sites are less aggressive). "
        f"If that fails, re-create your login profile with 'hyperresearch setup'.{escalated}"
    )
    _abort_blocked(
        msg,
        "AUTH_REQUIRED_ESCALATED",
        "AUTH_REQUIRED",
        item_id,
        json_output,
        "[red]Auth required:[/] ",
    )


def _escalate_junk(
    vault, url: str, junk_reason: str, tags: list, suggested_by: list, utility_score
):
    """Escalate bot-detection junk. Returns the escalation item id or None."""
    if not junk_reason.startswith("Bot detection"):
        return None
    reason = "captcha" if "captcha" in junk_reason.lower() else "bot_block"
    return _escalate_blocked(
        vault, url, reason, tags, suggested_by, utility_score, detail=junk_reason
    )


def _handle_junk(
    vault,
    prov,
    url: str,
    result,
    rescue: tuple,
    tags: list,
    suggested_by: list,
    utility_score,
    json_output: bool,
):
    """Junk-content path. Returns (result, reason, loc, doi)."""
    from hyperresearch.web.pdf import PDF_FAILURE_KEY

    rescue_reason, oa_location, rescue_doi = rescue
    junk_reason = result.looks_like_junk(vault.config.junk) if oa_location is None else None
    if not junk_reason:
        return result, rescue_reason, oa_location, rescue_doi
    rescued, reason, loc, doi = _attempt_rescue(
        vault, prov, url, junk_reason, result.raw_html, json_output
    )
    if rescued is not None:
        return rescued, reason, loc, doi
    item_id = _escalate_junk(vault, url, junk_reason, tags, suggested_by, utility_score)
    escalated = f" Queued for browser-lane escalation (#{item_id})." if item_id else ""
    pdf_failure = result.metadata.get(PDF_FAILURE_KEY)
    pdf_note = f" PDF lane: {pdf_failure}." if pdf_failure else ""
    msg = f"Skipped junk content from {url}: {junk_reason}.{pdf_note}{escalated}"
    _abort_blocked(
        msg, "JUNK_ESCALATED", "JUNK_CONTENT", item_id, json_output, "[yellow]Skipped:[/] "
    )


def _sync_if_needed(vault) -> None:
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)


def _build_extra_meta(
    url: str,
    domain: str,
    result,
    prov_name: str,
    detected_doi,
    oa_location,
    rescue_reason,
    utility_score,
) -> dict:
    from hyperresearch.core.oa import oa_frontmatter

    extra_meta = {
        "source": url,
        "source_domain": domain,
        "fetched_at": result.fetched_at.isoformat(),
        "fetch_provider": prov_name,
    }
    if result.metadata.get("author"):
        extra_meta["author"] = result.metadata["author"]
    if detected_doi:
        extra_meta["doi"] = detected_doi
    if oa_location is not None:
        extra_meta.update(
            oa_frontmatter(oa_location, kind="rescued" if rescue_reason else "substituted")
        )
    if utility_score is not None:
        extra_meta["utility_score"] = utility_score  # type: ignore[assignment]
    return extra_meta


def _prepend_breadcrumbs(body_content, suggested_by: list, suggested_by_reason) -> str:
    breadcrumb_lines = []
    reason_suffix = f" — {suggested_by_reason}" if suggested_by_reason else ""
    for src_id in suggested_by:
        src_id_clean = src_id.strip()
        if not src_id_clean:
            continue
        breadcrumb_lines.append(f"*Suggested by [[{src_id_clean}]]{reason_suffix}*")
    if breadcrumb_lines:
        return "\n".join(breadcrumb_lines) + "\n\n" + body_content
    return body_content


def _persist_raw_file(vault, result, note_path):
    """Save a raw (PDF, etc.) companion file and persist its reference."""
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
    from hyperresearch.core.frontmatter import parse_frontmatter, render_note

    note_text = note_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(note_text)
    if meta.raw_file != raw_file_path:
        meta.raw_file = raw_file_path
        note_path.write_text(render_note(meta, body), encoding="utf-8")
    return raw_file_path


def _unlink_quiet(path) -> None:
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def _drop_loser_files(note_path, vault, raw_file_path) -> None:
    _unlink_quiet(note_path)
    # Also unlink the raw file we wrote earlier — the winner already has its
    # own raw file under raw/<winner-id>.<ext>. Without this, the
    # orphaned-raw-files lint flags raw/<our-id>.<ext> and disk leaks accumulate.
    if raw_file_path:
        _unlink_quiet(vault.research_dir / raw_file_path)


def _resolve_source_race(vault, conn, url: str, note_id: str, note_path, raw_file_path):
    """Detect a duplicate-URL race; adopt the winner. Returns (note_id, note_path, raw_file_path)."""
    winner_row = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    if not (winner_row and winner_row["note_id"] != note_id):
        return note_id, note_path, raw_file_path
    winning_note_id = winner_row["note_id"]
    _drop_loser_files(note_path, vault, raw_file_path)
    # Re-sync to drop the orphan note row from the DB.
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    plan2 = compute_sync_plan(vault)
    if plan2.to_delete:
        execute_sync(vault, plan2)
    raw_file_path = None  # we no longer own a raw artifact for this fetch
    winner_path_row = conn.execute(
        "SELECT path FROM notes WHERE id = ?", (winning_note_id,)
    ).fetchone()
    if winner_path_row:
        note_path = vault.root / winner_path_row["path"]
    return winning_note_id, note_path, raw_file_path


def _maybe_save_assets(vault, conn, result, note_id: str, save_assets: bool) -> list:
    if not save_assets:
        return []
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


def _finalize_result(vault, prov, url: str, result, rescue: tuple):
    """OA substitution + source/domain bookkeeping. Returns (result, doi, domain, chars, rescue)."""
    from hyperresearch.core.oa import recover_full_text
    from hyperresearch.core.scholar import extract_doi

    rescue_reason, oa_location, rescue_doi = rescue
    detected_doi = (
        rescue_doi if oa_location is not None else extract_doi(url, result.raw_html, result.content)
    )
    original_domain = urlparse(url).netloc.lower() if oa_location is not None else result.domain
    original_chars = len(result.content or "")
    if oa_location is None:
        result, oa_location = recover_full_text(vault, prov, url, detected_doi, result)
    else:
        # Rescued above. Nothing was read from the source, so there is no
        # original length to report in the banner.
        original_chars = 0
    return result, detected_doi, original_domain, original_chars, rescue_reason, oa_location


def _write_note_files(
    vault,
    url: str,
    title,
    result,
    domain: str,
    extra_meta: dict,
    body_content,
    detected_tier: str,
    detected_content_type: str,
    tags: list,
    parent,
):
    """Write the note file + raw companion. Returns (note_path, note_title, raw_file_path)."""
    from hyperresearch.core.note import write_note

    note_title = title or result.title or urlparse(url).path.split("/")[-1] or "Untitled"
    note_path = write_note(
        vault.notes_dir,
        title=note_title,
        body=body_content,
        tags=tags,
        status="draft",
        source=url,
        parent=parent,
        tier=detected_tier,
        content_type=detected_content_type,
        run_tag=tags[0] if tags else None,
        extra_frontmatter=extra_meta,
    )
    return note_path, note_title, _persist_raw_file(vault, result, note_path)


def _record_and_resolve(
    vault, conn, url: str, domain: str, result, prov_name: str, note_path, raw_file_path
):
    """INSERT the source row, reclaim orphans, adopt a race winner. Returns (note_id, note_path, raw_file_path)."""
    note_id = note_path.stem
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
    conn.execute(
        """INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, note_id, domain, result.fetched_at.isoformat(), prov_name, content_hash),
    )
    reclaim_orphaned_source_row(
        conn, url, note_id, domain, result.fetched_at.isoformat(), prov_name, content_hash
    )
    conn.commit()
    return _resolve_source_race(vault, conn, url, note_id, note_path, raw_file_path)


def _build_fetch_data(
    url: str,
    vault,
    note_title: str,
    note_id: str,
    note_path,
    result,
    domain: str,
    prov_name: str,
    saved_assets: list,
    raw_file_path,
    oa_location,
    rescue_reason,
    original_chars: int,
) -> dict:
    data = {
        "note_id": note_id,
        "title": note_title,
        "url": url,
        "domain": domain,
        "provider": prov_name,
        "path": str(note_path.relative_to(vault.root)),
        "word_count": len(result.content.split()),
        "assets": saved_assets,
        "raw_file": raw_file_path,
    }
    if oa_location is not None:
        data["oa"] = {
            "url": oa_location.url,
            "resolver": oa_location.resolver,
            "version": oa_location.version,
            "license": oa_location.license,
            "replaced_chars": original_chars,
            "kind": "rescued" if rescue_reason else "substituted",
            "nothing_from_source": bool(rescue_reason),
            "blocked_reason": rescue_reason,
        }
    return data


def _print_oa_provenance(console_, oa_location, rescue_reason) -> None:
    console_.print(
        f"  [cyan]Body from:[/] {oa_location.url} "
        f"([bold]{oa_location.version or 'version unknown'}[/], via {oa_location.resolver})"
    )
    if rescue_reason:
        console_.print(
            f"  [yellow]Source was never read[/] ({rescue_reason}) — this whole "
            "note, title and authors included, is the open-access copy."
        )
    if not oa_location.is_version_of_record:
        console_.print(
            "  [yellow]Note:[/] this is not the version of record — "
            "check quotations against the published paper."
        )


def _report_fetch_saved(
    url: str,
    vault,
    note_title: str,
    note_id: str,
    data: dict,
    oa_location,
    rescue_reason,
    saved_assets: list,
    json_output: bool,
) -> None:
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
        return
    console.print(f"[green]Saved:[/] {note_title}")
    console.print(f"  ID: {note_id}")
    console.print(f"  Source: {url}")
    if oa_location is not None:
        _print_oa_provenance(console, oa_location, rescue_reason)
    console.print(f"  Words: {data['word_count']}")
    if saved_assets:
        console.print(f"  Assets: {len(saved_assets)} saved to output/assets/{note_id}/")


@app.command("fetch")
def fetch(
    url: str = typer.Argument(..., help="URL to fetch and save as a note"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags (repeatable)"),
    title: str | None = typer.Option(None, "--title", help="Override title"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    save_assets: bool = typer.Option(
        False, "--save-assets", "-a", help="Download images and screenshot"
    ),
    visible: bool = typer.Option(
        False, "--visible", "-V", help="Run browser visibly (for stubborn auth sites)"
    ),
    suggested_by: list[str] = typer.Option(
        [],
        "--suggested-by",
        help="Source note ID(s) that suggested this URL. Prepends a 'Suggested by [[note-id]]' breadcrumb to the new note's body, which the link extractor picks up as a wiki-link so the fetched note appears in the source's backlinks. Repeat for multiple sources.",
    ),
    suggested_by_reason: str | None = typer.Option(
        None,
        "--suggested-by-reason",
        help="One-line justification for why the suggesting source named this URL. Appears next to the [[source-id]] breadcrumb.",
    ),
    utility_score: float | None = typer.Option(
        None,
        "--utility-score",
        help="Step-2 fetch-selection utility score (0-18). Persisted to note frontmatter so the quality composite can use it after fetching.",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Fetch a URL and save its content as a research note."""
    from hyperresearch.web.base import get_provider

    vault = _open_fetch_vault(json_output)
    vault.auto_sync()
    conn = vault.db

    # An orphaned row (note deleted) is not a duplicate, so --suggested-by
    # never tries to append a breadcrumb to a note_id of None. Graceful
    # duplicate handling for the guided reading loop: with --suggested-by,
    # append the breadcrumb to the existing note instead of erroring out.
    if _handle_duplicate_note(vault, conn, url, suggested_by, suggested_by_reason, json_output):
        return

    visible = _maybe_auto_visible(url, visible, vault)

    # Fetch content
    prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
        headless=not visible,
        settings=vault.config.fetch,
        gates=vault.config.junk,
    )
    if not json_output:
        console.print(f"[dim]Fetching with {prov.name}...[/]")

    # Open-access rescue for blocked sources. A 403, a login wall or a bot wall
    # is where a paywalled paper is most completely lost — and, since the DOI
    # identifies the work rather than the host, most likely to have a legal
    # open-access copy sitting somewhere else.
    from hyperresearch.core.oa import recovery_notice

    result, rescue_reason, oa_location, rescue_doi = _fetch_initial_result(
        prov, vault, url, json_output
    )

    # Detect login redirects — abort, but ESCALATE to the browser lane
    # instead of silently losing the source.
    result, rescue_reason, oa_location, rescue_doi = _handle_login_wall(
        vault,
        prov,
        url,
        result,
        (rescue_reason, oa_location, rescue_doi),
        tags,
        suggested_by,
        utility_score,
        json_output,
    )

    # Detect junk pages — captcha, error pages, binary garbage, empty content.
    # Bot-detection junk (Cloudflare/captcha walls) escalates to the browser
    # lane; content-quality junk (error pages, empty content) does not — a
    # 404 in Chrome is still a 404.
    result, rescue_reason, oa_location, rescue_doi = _handle_junk(
        vault,
        prov,
        url,
        result,
        (rescue_reason, oa_location, rescue_doi),
        tags,
        suggested_by,
        utility_score,
        json_output,
    )

    # Source-ranking capture: DOI/arXiv id + the orchestrator's utility score.
    # On a rescue, the DOI we resolved with is the authority — re-extracting
    # would read it out of the substitute's body instead. Open-access
    # recovery swaps a thin paywalled result for a legal full-text copy.
    result, detected_doi, domain, original_chars, rescue_reason, oa_location = _finalize_result(
        vault, prov, url, result, (rescue_reason, oa_location, rescue_doi)
    )

    # Write note
    detected_content_type = _detect_content_type(url, result.raw_content_type)
    detected_tier = _detect_tier(url, detected_content_type)
    extra_meta = _build_extra_meta(
        url, domain, result, prov.name, detected_doi, oa_location, rescue_reason, utility_score
    )

    # Build body with backlink breadcrumb if this fetch was suggested by another note.
    # Prepending `*Suggested by [[source-id]] — reason*` lines creates wiki-links the
    # normal link extractor will pick up, so the new note automatically appears in
    # graph backlinks of its suggester(s). Zero schema change needed.
    body_content = _prepend_breadcrumbs(result.content, suggested_by, suggested_by_reason)

    # The recovery banner goes above everything else in the body — a reader
    # must not have to scroll or check frontmatter to learn that these bytes
    # came from somewhere other than `source:`.
    if oa_location is not None:
        body_content = (
            recovery_notice(oa_location, url, original_chars, blocked_reason=rescue_reason)
            + "\n"
            + body_content
        )

    # Save raw file (PDF, etc.) if present. Note: tagging and summarization
    # is the agent's job, not an automatic process.
    note_path, note_title, raw_file_path = _write_note_files(
        vault,
        url,
        title,
        result,
        domain,
        extra_meta,
        body_content,
        detected_tier,
        detected_content_type,
        tags,
        parent,
    )

    # Sync first so the note exists in the notes table (needed for FK on sources/assets).
    _sync_if_needed(vault)

    # Record source in DB. Use INSERT OR IGNORE to survive a duplicate-URL
    # race: two parallel fetches on the same URL both pass the earlier
    # duplicate-check SELECT, both try to INSERT, and without IGNORE the
    # second crashes with IntegrityError leaving a stray .md file and
    # notes row but no sources row. With IGNORE the second INSERT is a
    # no-op and we detect the race by re-selecting the row afterward.
    # An orphaned row (note deleted → ON DELETE SET NULL) also makes that
    # INSERT a no-op, but nobody owns the url, so claim it.
    note_id, note_path, raw_file_path = _record_and_resolve(
        vault, conn, url, domain, result, prov.name, note_path, raw_file_path
    )

    # Save assets (screenshot + images) — only when requested
    saved_assets = _maybe_save_assets(vault, conn, result, note_id, save_assets)

    _credit_run_spend(vault, tags)

    data = _build_fetch_data(
        url,
        vault,
        note_title,
        note_id,
        note_path,
        result,
        domain,
        prov.name,
        saved_assets,
        raw_file_path,
        oa_location,
        rescue_reason,
        original_chars,
    )
    _report_fetch_saved(
        url, vault, note_title, note_id, data, oa_location, rescue_reason, saved_assets, json_output
    )


def _escalate_blocked(
    vault,
    url: str,
    reason: str,
    tags: list[str],
    suggested_by: list[str],
    utility_score: float | None,
    detail: str | None = None,
) -> int | None:
    """Queue a blocked fetch for the Chrome lane. Never raises — a failed
    enqueue must not mask the original fetch outcome."""
    try:
        from hyperresearch.core.escalation import maybe_enqueue_blocked_fetch

        return maybe_enqueue_blocked_fetch(
            vault,
            url,
            reason,
            vault_tag=tags[0] if tags else None,
            suggested_by=suggested_by[0] if suggested_by else None,
            utility_score=utility_score,
            detail=detail,
        )
    except Exception:
        return None


def _save_screenshot(conn, result, note_id: str, assets_dir: Path, now: str) -> dict | None:
    """Persist the page screenshot. Returns its asset info, or None when absent."""
    if not result.screenshot:
        return None
    assets_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = assets_dir / "screenshot.png"
    screenshot_path.write_bytes(result.screenshot)
    conn.execute(
        """INSERT INTO assets (note_id, type, filename, alt_text, content_type, size_bytes, created_at)
           VALUES (?, 'screenshot', ?, 'Page screenshot', 'image/png', ?, ?)""",
        (note_id, str(screenshot_path), len(result.screenshot), now),
    )
    return {
        "type": "screenshot",
        "path": str(screenshot_path),
        "size_bytes": len(result.screenshot),
    }


def _content_image_candidates(media: list[dict]) -> list[dict]:
    """Content-relevant image entries: http(s) URLs, no junk patterns, no SVGs."""
    candidates = []
    for img in media:
        img_url = img.get("src", "")
        if not img_url or not img_url.startswith("http"):
            continue
        url_lower = img_url.lower()
        if any(skip in url_lower for skip in SKIP_URL_PATTERNS):
            continue
        # Skip SVGs (usually icons/diagrams that don't render well saved)
        if url_lower.endswith(".svg"):
            continue
        candidates.append(img)
    return candidates


def _download_top_images(
    conn, result, note_id, assets_dir, now, settings, timeout_s, image_cap, allow_private
) -> list:
    """Download the top-N content images. Returns their asset infos."""
    # Filter out junk before sorting, sort by score descending, take top N
    candidates = _content_image_candidates(result.media)
    candidates.sort(key=lambda m: m.get("score", 0), reverse=True)
    downloaded = []
    for img in candidates[: settings.max_images]:
        asset_info = _download_image(
            conn,
            note_id,
            img.get("src", ""),
            img.get("alt", "") or "",
            assets_dir,
            now,
            min_image_bytes=settings.min_image_bytes,
            timeout_s=timeout_s,
            max_image_bytes=image_cap,
            allow_private_hosts=allow_private,
        )
        if asset_info:
            downloaded.append(asset_info)
    return downloaded


def _save_assets(
    conn,
    result,
    note_id: str,
    assets_dir: Path,
    settings: AssetSettings | None = None,
    image_timeout_s: int | None = None,
    max_image_bytes: int | None = None,
    allow_private_hosts: tuple[str, ...] | None = None,
) -> list[dict]:
    """Save screenshot and images to assets dir, record in DB. Returns list of saved asset info."""
    settings = settings or AssetSettings()
    fetch_defaults = FetchSettings()
    timeout_s = image_timeout_s if image_timeout_s is not None else fetch_defaults.image_timeout_s
    image_cap = max_image_bytes if max_image_bytes is not None else fetch_defaults.max_image_bytes
    allow_private = (
        allow_private_hosts
        if allow_private_hosts is not None
        else fetch_defaults.allow_private_hosts
    )
    saved: list[dict] = []
    now = datetime.now(UTC).isoformat()

    screenshot_info = _save_screenshot(conn, result, note_id, assets_dir, now)
    if screenshot_info is not None:
        saved.append(screenshot_info)

    # Download images — only content-relevant ones
    if result.media:
        saved.extend(
            _download_top_images(
                conn,
                result,
                note_id,
                assets_dir,
                now,
                settings,
                timeout_s,
                image_cap,
                allow_private,
            )
        )

    if saved:
        conn.commit()

    return saved


def _download_image(
    conn,
    note_id: str,
    img_url: str,
    alt: str,
    assets_dir: Path,
    now: str,
    min_image_bytes: int = 50_000,
    timeout_s: int = 15,
    max_image_bytes: int | None = None,
    allow_private_hosts: tuple[str, ...] = (),
) -> dict | None:
    """Download a single image. Returns asset info dict or None if skipped."""
    # Generate filename from URL
    parsed = urlparse(img_url)
    url_path = parsed.path.rstrip("/")
    ext = Path(url_path).suffix.lower() if url_path else ""
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"):
        ext = ".jpg"

    # Clean filename from URL path
    raw_name = Path(url_path).stem if url_path else "image"
    clean_name = re.sub(r"[^\w\-.]", "_", raw_name)[:80]
    filename = f"{clean_name}{ext}"

    assets_dir.mkdir(parents=True, exist_ok=True)
    file_path = assets_dir / filename

    # Handle collision
    counter = 2
    while file_path.exists():
        file_path = assets_dir / f"{clean_name}-{counter}{ext}"
        counter += 1

    from hyperresearch.web.safe_http import MAX_BYTES_IMAGE, SafeHTTPError, safe_get

    try:
        resp = safe_get(
            img_url,
            max_bytes=max_image_bytes if max_image_bytes is not None else MAX_BYTES_IMAGE,
            timeout=timeout_s,
            allow_private_hosts=allow_private_hosts,
        )
        data = resp.content
        content_type = resp.headers.get("content-type", "")
    except SafeHTTPError as exc:
        # A gate refusal (SSRF / size cap) is a security event, not a skip —
        # it must be visible, unlike routine 404s and timeouts below. Printed
        # to stderr: this helper has no json_output flag, and stdout must stay
        # pure JSON in --json mode.
        err_console.print(f"  [yellow]Image refused by fetch gate:[/] {img_url} — {exc}")
        return None
    except Exception:
        return None

    # Skip tiny images (icons, spacers, tracking pixels)
    if len(data) < min_image_bytes:
        return None

    file_path.write_bytes(data)

    conn.execute(
        """INSERT INTO assets (note_id, type, filename, url, alt_text, content_type, size_bytes, created_at)
           VALUES (?, 'image', ?, ?, ?, ?, ?, ?)""",
        (note_id, str(file_path), img_url, alt, content_type, len(data), now),
    )

    return {
        "type": "image",
        "path": str(file_path),
        "url": img_url,
        "alt": alt,
        "size_bytes": len(data),
    }
