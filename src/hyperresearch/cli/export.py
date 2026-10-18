"""Export CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import success

app = typer.Typer()


def _collect_export_notes(vault) -> list:
    notes = []
    for row in vault.db.execute(
        "SELECT n.*, nc.body FROM notes n JOIN note_content nc ON n.id = nc.note_id ORDER BY n.title"
    ):
        tags = [
            r["tag"]
            for r in vault.db.execute("SELECT tag FROM tags WHERE note_id = ?", (row["id"],))
        ]
        notes.append(
            {
                "id": row["id"],
                "title": row["title"],
                "path": row["path"],
                "status": row["status"],
                "type": row["type"],
                "tags": tags,
                "created": row["created"],
                "updated": row["updated"],
                "word_count": row["word_count"],
                "source": row["source"],
                "parent": row["parent"],
                "summary": row["summary"],
                "body": row["body"],
            }
        )
    return notes


def _write_export_file(out: Path, notes: list, pretty: bool) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if pretty else None
    out.write_text(json.dumps(notes, indent=indent, default=str), encoding="utf-8")


def _report_export(vault, out: Path, notes: list, json_output: bool) -> None:
    if json_output:
        output(
            success({"path": str(out), "count": len(notes)}, vault=str(vault.root)), json_mode=True
        )
    else:
        console.print(f"[green]Exported {len(notes)} notes to:[/] {out}")


@app.command("json")
def export_json(
    output_path: str | None = typer.Option(None, "--output", "-o", help="Output file path"),
    pretty: bool = typer.Option(True, "--pretty/--compact", help="Pretty print"),
    json_output: bool = typer.Option(False, "--json", help="JSON output for status"),
) -> None:
    """Export all notes as structured JSON."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    notes = _collect_export_notes(vault)
    out = Path(output_path) if output_path else vault.exports_dir / "vault.json"
    _write_export_file(out, notes, pretty)
    _report_export(vault, out, notes, json_output)


_EXPORT_FILTERS = (
    ("tag", "n.id IN (SELECT note_id FROM tags WHERE tag = ?)"),
    ("status", "n.status = ?"),
)


def _build_export_filters(tag, status, parent) -> tuple:
    clauses = ["n.type NOT IN ('index')"]
    params: list = []
    values = {"tag": tag.lower() if tag else None, "status": status}
    for key, clause in _EXPORT_FILTERS:
        if values[key]:
            clauses.append(clause)
            params.append(values[key])
    if parent:
        clauses.append("(n.parent = ? OR n.parent LIKE ?)")
        params.append(parent)
        params.append(parent + "/%")
    return clauses, params


def _copy_export_rows(vault, rows, out_dir, dry_run: bool) -> list:
    import shutil

    exported = []
    for row in rows:
        src = vault.root / row["path"]
        if not src.exists():
            continue
        dest = out_dir / row["path"]
        exported.append({"id": row["id"], "path": row["path"]})
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    return exported


def _report_exported(vault, out_dir, exported: list, dry_run: bool, json_output: bool) -> None:
    if json_output:
        action = "would_export" if dry_run else "exported"
        output(
            success(
                {action: exported, "count": len(exported), "output_path": str(out_dir)},
                count=len(exported),
                vault=str(vault.root),
            ),
            json_mode=True,
        )
        return
    verb = "Would export" if dry_run else "Exported"
    console.print(f"[green]{verb} {len(exported)} notes to:[/] {out_dir}")
    for item in exported[:20]:
        console.print(f"  {item['path']}")
    if len(exported) > 20:
        console.print(f"  [dim]...and {len(exported) - 20} more[/]")


@app.command("vault")
def export_vault(
    output_path: str = typer.Argument(..., help="Output directory"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent topic"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be exported"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Export a subset of notes to another directory."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    clauses, params = _build_export_filters(tag, status, parent)
    where = " AND ".join(clauses)
    rows = vault.db.execute(f"SELECT id, path, title FROM notes n WHERE {where}", params).fetchall()

    out_dir = Path(output_path).resolve()
    exported = _copy_export_rows(vault, rows, out_dir, dry_run)
    _report_exported(vault, out_dir, exported, dry_run, json_output)
