"""Import notes from another vault or directory."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def _open_import_vault(json_output: bool):
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _resolve_source_dir(source: str, json_output: bool):
    source_path = Path(source).resolve()
    if source_path.is_dir():
        return source_path
    msg = f"Source directory not found: {source}"
    if json_output:
        output(error(msg, "NOT_FOUND"), json_mode=True)
    else:
        console.print(f"[red]{msg}[/]")
    raise typer.Exit(1)


def _find_import_files(source_path) -> list:
    md_files = sorted(source_path.rglob("*.md"))
    # Skip .hyperresearch/, templates/ etc. from source
    skip_dirs = {".hyperresearch", ".git", ".venv", "node_modules", "templates"}
    return [
        f
        for f in md_files
        if not any(part in skip_dirs for part in f.relative_to(source_path).parts)
    ]


def _report_no_imports(vault, json_output: bool) -> None:
    if json_output:
        output(success({"imported": [], "count": 0}, vault=str(vault.root)), json_mode=True)
    else:
        console.print("[dim]No markdown files found in source.[/]")


def _copy_import_files(vault, md_files: list, source_path, prefix: str, dry_run: bool) -> list:
    imported = []
    for src_file in md_files:
        rel = src_file.relative_to(source_path).as_posix()
        dest_rel = f"{prefix}/{rel}" if prefix else rel
        # Write into output/notes/, not vault root
        dest = vault.notes_dir / dest_rel
        imported.append({"source": rel, "destination": dest_rel})
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)
    return imported


def _print_imported(imported: list, dry_run: bool) -> None:
    verb = "Would import" if dry_run else "Imported"
    console.print(f"[green]{verb} {len(imported)} files:[/]")
    for item in imported[:20]:
        console.print(f"  {item['source']} -> {item['destination']}")
    if len(imported) > 20:
        console.print(f"  [dim]...and {len(imported) - 20} more[/]")


def _report_imported(vault, imported: list, dry_run: bool, json_output: bool) -> None:
    if json_output:
        action = "would_import" if dry_run else "imported"
        output(
            success(
                {action: imported, "count": len(imported)},
                count=len(imported),
                vault=str(vault.root),
            ),
            json_mode=True,
        )
    else:
        _print_imported(imported, dry_run)


def import_vault(
    source: str = typer.Argument(..., help="Source directory to import from"),
    prefix: str = typer.Option(
        "", "--prefix", "-p", help="Path prefix for imported notes (e.g. imported/ml)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be imported"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Import markdown notes from another directory into this vault."""
    vault = _open_import_vault(json_output)
    source_path = _resolve_source_dir(source, json_output)
    md_files = _find_import_files(source_path)

    if not md_files:
        _report_no_imports(vault, json_output)
        return

    imported = _copy_import_files(vault, md_files, source_path, prefix, dry_run)
    if not dry_run:
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        plan = compute_sync_plan(vault)
        execute_sync(vault, plan)
    _report_imported(vault, imported, dry_run, json_output)
