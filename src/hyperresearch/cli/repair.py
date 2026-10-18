"""Repair command — fix and rebuild everything in one shot."""

from __future__ import annotations

from datetime import UTC

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.note import NoteStatus
from hyperresearch.models.output import error, success


def _open_vault(json_output: bool):
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


def _resync(vault) -> None:
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    execute_sync(vault, compute_sync_plan(vault))


def _repair_sync(vault, report: dict, json_output: bool) -> None:
    if not json_output:
        console.print("[bold]1/6 Syncing...[/]")
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    plan = compute_sync_plan(vault, force=True)
    result = execute_sync(vault, plan)
    report["sync"] = {
        "added": result.added,
        "updated": result.updated,
        "deleted": result.deleted,
        "errors": len(result.errors),
    }
    if not json_output:
        console.print(
            f"  +{result.added} ~{result.updated} -{result.deleted} ({result.duration_ms:.0f}ms)"
        )


def _stub_broken_link(vault, target: str) -> bool:
    from hyperresearch.core.note import stub_summary, write_note

    title = target.replace("-", " ").replace("_", " ").title()
    try:
        # Sideline stubs to output/temp/ — see note in cli/graph.py
        write_note(
            vault.temp_dir,
            title,
            body=f"# {title}\n\n*Stub — created to resolve a broken link. Expand this note.*\n",
            note_id=target,
            status="draft",
            summary=stub_summary(target),
        )
        return True
    except Exception:
        return False


def _repair_stubs(vault, report: dict, stub_broken: bool, json_output: bool) -> None:
    if not stub_broken:
        if not json_output:
            console.print("[dim]2/6 Skipping stubs[/]")
        return
    if not json_output:
        console.print("[bold]2/6 Stubbing broken links...[/]")
    rows = vault.db.execute(
        "SELECT DISTINCT target_ref FROM links WHERE target_id IS NULL"
    ).fetchall()
    stubs_created = sum(1 for row in rows if _stub_broken_link(vault, row["target_ref"]))
    if stubs_created:
        _resync(vault)
    report["stubs"] = stubs_created
    if not json_output:
        console.print(f"  {stubs_created} stubs created")


def _enrich_note(vault, row, tag_vocab: list) -> bool:
    from datetime import datetime as _dt

    from hyperresearch.core.enrich import auto_summary, auto_tag
    from hyperresearch.core.frontmatter import parse_frontmatter as _parse_fm
    from hyperresearch.core.frontmatter import serialize_frontmatter as _ser_fm
    from hyperresearch.core.note import strip_markdown

    fp = vault.root / row["path"]
    meta, body = _parse_fm(fp.read_text(encoding="utf-8-sig"))
    changed = False
    if not meta.tags:
        suggested = auto_tag(strip_markdown(body), tag_vocab)
        if suggested:
            meta.tags = suggested
            changed = True
    if not meta.summary or not meta.summary.strip():
        summary_suggested = auto_summary(body)
        if summary_suggested:
            meta.summary = summary_suggested
            changed = True
    if changed:
        meta.updated = _dt.now(UTC)
        fp.write_text(_ser_fm(meta) + "\n" + body, encoding="utf-8")
    return changed


def _repair_enrich(vault, report: dict, enrich: bool, json_output: bool) -> None:
    if not enrich:
        if not json_output:
            console.print("[dim]3/6 Skipping enrichment[/]")
        return
    if not json_output:
        console.print("[bold]3/6 Enriching metadata...[/]")
    tag_vocab = [
        {"tag": r["tag"], "count": r["c"]}
        for r in vault.db.execute(
            "SELECT tag, COUNT(*) as c FROM tags GROUP BY tag ORDER BY c DESC"
        )
    ]
    # Find notes missing tags or summary
    deficient = vault.db.execute(
        "SELECT n.id, n.path, n.summary FROM notes n "
        "LEFT JOIN note_content nc ON n.id = nc.note_id "
        "WHERE n.type NOT IN ('index', 'raw') AND ("
        "  n.id NOT IN (SELECT DISTINCT note_id FROM tags) OR "
        "  n.summary IS NULL OR LENGTH(TRIM(COALESCE(n.summary, ''))) = 0"
        ")"
    ).fetchall()
    enriched_count = 0
    for row in deficient:
        try:
            if _enrich_note(vault, row, tag_vocab):
                enriched_count += 1
        except Exception:
            pass
    if enriched_count:
        _resync(vault)
    report["enriched"] = enriched_count
    if not json_output:
        console.print(f"  {enriched_count} notes enriched")


def _promote_rows(vault, rows, status) -> int:
    from datetime import datetime

    from hyperresearch.core.frontmatter import parse_frontmatter, serialize_frontmatter

    promoted = 0
    for row in rows:
        try:
            fp = vault.root / row["path"]
            meta, body = parse_frontmatter(fp.read_text(encoding="utf-8-sig"))
            meta.status = status
            meta.updated = datetime.now(UTC)
            fp.write_text(serialize_frontmatter(meta) + "\n" + body, encoding="utf-8")
            promoted += 1
        except Exception:
            pass
    return promoted


def _repair_promote(vault, report: dict, promote_notes: bool, json_output: bool) -> None:
    if not promote_notes:
        if not json_output:
            console.print("[dim]4/6 Skipping promotion[/]")
        return
    if not json_output:
        console.print("[bold]4/6 Promoting notes...[/]")
    drafts = vault.db.execute("""
        SELECT n.id, n.path FROM notes n
        WHERE n.status = 'draft' AND n.type NOT IN ('index')
          AND n.word_count >= 50
          AND n.summary IS NOT NULL AND LENGTH(n.summary) > 0
          AND n.id IN (SELECT note_id FROM tags)
    """).fetchall()
    reviews = vault.db.execute("""
        SELECT n.id, n.path FROM notes n
        WHERE n.status = 'review' AND n.type NOT IN ('index')
          AND n.word_count >= 100
          AND (n.id IN (SELECT DISTINCT source_id FROM links)
               OR n.id IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL))
    """).fetchall()
    promoted_count = _promote_rows(vault, drafts, NoteStatus.REVIEW)
    promoted_count += _promote_rows(vault, reviews, NoteStatus.EVERGREEN)
    if promoted_count:
        _resync(vault)
    report["promoted"] = promoted_count
    if not json_output:
        console.print(f"  {promoted_count} notes promoted")


def _repair_indexes(vault, report: dict, rebuild_index: bool, json_output: bool) -> None:
    if not rebuild_index:
        if not json_output:
            console.print("[dim]5/6 Skipping indexes[/]")
        return
    if not json_output:
        console.print("[bold]5/6 Rebuilding indexes...[/]")
    from hyperresearch.indexgen.generator import IndexGenerator

    built = IndexGenerator(vault).build_all()
    # Sync the new index pages
    _resync(vault)
    report["indexes"] = len(built)
    if not json_output:
        console.print(f"  {len(built)} index pages built")


def _repair_ranking(vault, report: dict, json_output: bool) -> None:
    # Recompute derived ranking scores (centrality + quality). Cheap,
    # pure-local, and keeps the score cache fresh after a force-sync
    # rebuilt the DB from markdown.
    from hyperresearch.core.graphrank import compute_centrality
    from hyperresearch.core.quality import compute_quality_scores

    ranked = compute_centrality(vault.db)
    compute_quality_scores(vault.db, vault.config.ranking)
    report["centrality_ranked"] = ranked
    if not json_output and ranked:
        console.print(f"  centrality + quality recomputed for {ranked} notes")


def _repair_docs(vault, report: dict, update_docs: bool, json_output: bool) -> None:
    if not update_docs:
        if not json_output:
            console.print("[dim]6/6 Skipping agent docs[/]")
        return
    if not json_output:
        console.print("[bold]6/6 Updating agent docs...[/]")
    from hyperresearch.core.agent_docs import inject_agent_docs

    modified = inject_agent_docs(vault.root)
    report["agent_docs"] = modified
    if not json_output:
        _report_modified_docs(modified)


def _report_modified_docs(modified: list) -> None:
    if modified:
        for m in modified:
            console.print(f"  {m}")
    else:
        console.print("  Already up to date")


def _repair_health(vault, report: dict, json_output: bool) -> None:
    broken = vault.db.execute("SELECT COUNT(*) as c FROM links WHERE target_id IS NULL").fetchone()[
        "c"
    ]
    orphans = vault.db.execute("""
        SELECT COUNT(*) as c FROM notes n
        WHERE n.type NOT IN ('index', 'raw')
          AND n.id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)
          AND n.id NOT IN (SELECT DISTINCT source_id FROM links)
    """).fetchone()["c"]
    total = vault.db.execute(
        "SELECT COUNT(*) as c FROM notes WHERE type NOT IN ('index')"
    ).fetchone()["c"]
    report["health"] = {"total_notes": total, "broken_links": broken, "orphans": orphans}
    if json_output:
        output(success(report, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"\n[bold]Done.[/] {total} notes, {broken} broken links, {orphans} orphans.")


def repair(
    stub_broken: bool = typer.Option(
        True, "--stub/--no-stub", help="Create stubs for broken links"
    ),
    enrich: bool = typer.Option(
        True, "--enrich/--no-enrich", help="Auto-tag and auto-summarize notes"
    ),
    promote_notes: bool = typer.Option(
        True, "--promote/--no-promote", help="Auto-promote qualifying notes"
    ),
    rebuild_index: bool = typer.Option(True, "--index/--no-index", help="Rebuild index pages"),
    update_docs: bool = typer.Option(True, "--docs/--no-docs", help="Update CLAUDE.md"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Repair and rebuild the vault — full sync, fix broken links, promote notes, rebuild indexes."""
    vault = _open_vault(json_output)
    report: dict = {}

    _repair_sync(vault, report, json_output)
    _repair_stubs(vault, report, stub_broken, json_output)

    _repair_enrich(vault, report, enrich, json_output)
    _repair_promote(vault, report, promote_notes, json_output)
    _repair_indexes(vault, report, rebuild_index, json_output)
    _repair_ranking(vault, report, json_output)
    _repair_docs(vault, report, update_docs, json_output)
    _repair_health(vault, report, json_output)
