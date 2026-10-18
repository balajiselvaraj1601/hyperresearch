"""Link command — auto-discover and insert wiki-links between related notes."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


def _open_link_vault(json_output: bool):
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _resolve_link_targets(vault, tag, note_ids, auto: bool, json_output: bool):
    ids_to_process = list(note_ids) if note_ids else None
    if tag and not ids_to_process:
        rows = vault.db.execute("SELECT note_id FROM tags WHERE tag = ?", (tag.lower(),)).fetchall()
        ids_to_process = [r["note_id"] for r in rows]
    if not auto and not ids_to_process:
        if json_output:
            output(
                error("Use --auto to link all notes, or --note/--tag to filter", "NO_INPUT"),
                json_mode=True,
            )
        else:
            console.print("[yellow]Use --auto to link all notes, or --note/--tag to filter.[/]")
        raise typer.Exit(1)
    return ids_to_process


def _sync_link_report(vault, report: dict, dry_run: bool) -> None:
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    # Sync to pick up the modified files
    if report and not dry_run:
        plan = compute_sync_plan(vault)
        if plan.to_add or plan.to_update:
            execute_sync(vault, plan)


def _report_links(vault, report: dict, json_output: bool) -> None:
    total_links = sum(len(v) for v in report.values())
    if json_output:
        output(
            success(
                {"links_added": report, "notes_modified": len(report), "total_links": total_links},
                vault=str(vault.root),
            ),
            json_mode=True,
        )
        return
    if report:
        for nid, linked in report.items():
            console.print(f"  [green]+[/] {nid} → {', '.join(linked)}")
        console.print(f"\n[bold]{total_links} links added across {len(report)} notes.[/]")
    else:
        console.print("[dim]No new links found.[/]")


@app.callback(invoke_without_command=True)
def link(
    ctx: typer.Context,
    auto: bool = typer.Option(False, "--auto", "-a", help="Auto-link all notes"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Only process notes with this tag"),
    note_ids: list[str] = typer.Option([], "--note", "-n", help="Only process specific notes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what links would be added"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Auto-discover and insert wiki-links between related notes."""
    if ctx.invoked_subcommand is not None:
        return

    from hyperresearch.core.linker import auto_link

    vault = _open_link_vault(json_output)
    vault.auto_sync()

    ids_to_process = _resolve_link_targets(vault, tag, note_ids, auto, json_output)
    report = auto_link(vault, ids_to_process)
    _sync_link_report(vault, report, dry_run)
    _report_links(vault, report, json_output)
