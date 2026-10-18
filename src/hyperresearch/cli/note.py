"""Note CRUD CLI commands."""

from __future__ import annotations

from datetime import UTC

import typer

from hyperresearch.cli._output import console, output, print_note_summary
from hyperresearch.models.output import error, success

app = typer.Typer()

_LIST_FILTERS = (
    ("status", "n.status = ?"),
    ("note_type", "n.type = ?"),
    ("parent", "n.parent = ?"),
    ("tier", "n.tier = ?"),
    ("content_type", "n.content_type = ?"),
)


def _validate_note_enum(value, enum_cls, flag: str, code: str, json_output: bool) -> None:
    """Validate an enum option up-front, reporting INVALID_* and exiting 1."""
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


def _note_not_found(note_id: str, json_output: bool, message: str = "Not found") -> None:
    if json_output:
        output(error(f"Note not found: {note_id}", "NOT_FOUND"), json_mode=True)
    else:
        console.print(f"[red]{message}:[/] {note_id}")
    raise typer.Exit(1)


def _sync_notes(vault) -> None:
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    execute_sync(vault, compute_sync_plan(vault))


def _resolve_note_body(body_file, body_stdin: bool, body_text, title: str) -> str:
    """Determine body content from --body[-file|-stdin], defaulting to a heading."""
    import sys
    from pathlib import Path as P

    if body_file:
        return P(body_file).read_text(encoding="utf-8")
    if body_stdin:
        return sys.stdin.read()
    if body_text:
        return body_text
    return f"# {title}\n\n"


def _warn_similar_notes(similar: list, json_output: bool) -> None:
    if not similar or json_output:
        return
    for s in similar:
        console.print(f"[yellow]Similar note exists:[/] {s['id']} — {s['title']}")


def _write_plain_note(
    vault,
    title: str,
    body: str,
    tags,
    status: str,
    note_type: str,
    parent,
    summary,
    source,
    tier,
    content_type,
):
    from hyperresearch.core.note import write_note

    return write_note(
        vault.notes_dir,
        title,
        body=body,
        tags=tags,
        status=status,
        note_type=note_type,
        parent=parent,
        summary=summary,
        source=source,
        tier=tier,
        content_type=content_type,
    )


def _create_templated_note(
    vault,
    template: str,
    title: str,
    nid: str,
    body: str,
    tags,
    status: str,
    note_type: str,
    parent,
    summary,
    source,
    tier,
    content_type,
):
    """Create via template, or fall back to a plain note. Returns (path, nid)."""
    from hyperresearch.core.templates import get_template, render_template
    from hyperresearch.models.note import slugify

    tpl = get_template(template, vault.templates_dir)
    if tpl is None:
        console.print(f"[yellow]Template '{template}' not found, using default.[/]")
        return (
            _write_plain_note(
                vault,
                title,
                body,
                tags,
                status,
                note_type,
                parent,
                summary,
                source,
                tier,
                content_type,
            ),
            nid,
        )
    rendered = render_template(tpl, title, nid, tags)
    target_dir = vault.notes_dir
    if parent:
        target_dir = target_dir / slugify(parent)
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{nid}.md"
    counter = 2
    while file_path.exists():
        file_path = target_dir / f"{nid}-{counter}.md"
        nid = f"{nid}-{counter}"
        counter += 1
    file_path.write_text(rendered, encoding="utf-8")
    return file_path, nid


def _report_note_created(
    vault, nid: str, rel: str, title: str, similar: list, json_output: bool
) -> None:
    if not json_output:
        console.print(f"[green]Created:[/] {rel}")
        return
    data: dict = {"id": nid, "path": rel, "title": title}
    if similar:
        data["warning"] = f"Similar note already exists: {similar[0]['id']}"
        data["similar"] = [{"id": r["id"], "title": r["title"]} for r in similar]
    top_tags = vault.db.execute(
        "SELECT tag, COUNT(*) as c FROM tags GROUP BY tag ORDER BY c DESC LIMIT 30"
    ).fetchall()
    if top_tags:
        data["existing_tags"] = [r["tag"] for r in top_tags]
    output(success(data, vault=str(vault.root)), json_mode=True)


def _open_in_editor(path) -> None:
    import os
    import subprocess

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(path)])


@app.command("new")
def note_new(
    title: str = typer.Argument(..., help="Note title"),
    body_text: str | None = typer.Option(None, "--body", "-b", help="Note body content (markdown)"),
    body_file: str | None = typer.Option(
        None, "--body-file", "-B", help="Read body from file path"
    ),
    body_stdin: bool = typer.Option(False, "--body-stdin", help="Read body from stdin"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    note_type: str = typer.Option("note", "--type", help="Note type"),
    status: str = typer.Option("draft", "--status", "-s", help="Initial status"),
    summary: str | None = typer.Option(None, "--summary", help="One-line summary"),
    source: str | None = typer.Option(None, "--source", help="Source URL or path"),
    tier: str | None = typer.Option(
        None,
        "--tier",
        help="Epistemic tier: ground_truth|institutional|practitioner|commentary|unknown",
    ),
    content_type: str | None = typer.Option(
        None,
        "--content-type",
        help="Artifact kind: paper|docs|article|blog|forum|dataset|policy|code|book|transcript|review|unknown",
    ),
    template: str | None = typer.Option(
        None, "--template", "-T", help="Template: note|concept|reference|guide|comparison|moc"
    ),
    edit: bool = typer.Option(False, "--edit", "-e", help="Open in $EDITOR"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Create a new note.

    Body content: use --body for short text, --body-file for longer content
    (avoids shell escaping), or --body-stdin to pipe it in.
    """
    from hyperresearch.core.vault import Vault
    from hyperresearch.models.note import ContentType, Tier, slugify

    # Validate enums up-front so invalid values fail clearly
    _validate_note_enum(tier, Tier, "--tier", "INVALID_TIER", json_output)
    _validate_note_enum(
        content_type, ContentType, "--content-type", "INVALID_CONTENT_TYPE", json_output
    )

    vault = Vault.discover()
    vault.auto_sync()

    body = _resolve_note_body(body_file, body_stdin, body_text, title)
    nid = slugify(title)

    # Check for duplicate before creating (warn but still create — agent can decide)
    similar = vault.db.execute(
        "SELECT id, title FROM notes WHERE id = ? OR LOWER(title) = LOWER(?)",
        (nid, title),
    ).fetchall()
    _warn_similar_notes(similar, json_output)

    if template:
        path, nid = _create_templated_note(
            vault,
            template,
            title,
            nid,
            body,
            tags,
            status,
            note_type,
            parent,
            summary,
            source,
            tier,
            content_type,
        )
    else:
        path = _write_plain_note(
            vault, title, body, tags, status, note_type, parent, summary, source, tier, content_type
        )

    # Sync the new file into the DB so type/tags are indexed immediately
    _sync_notes(vault)

    # Read back the note ID (may have been collision-adjusted)
    from hyperresearch.core.note import read_note

    note = read_note(path, vault.root)
    nid = note.meta.id

    _report_note_created(
        vault, nid, path.relative_to(vault.root).as_posix(), title, similar, json_output
    )

    if edit:
        _open_in_editor(path)


def _attach_oa_info(row, data: dict) -> None:
    # Open-access substitution. Surfaced structurally, not just as the
    # banner in the body, so a reader checking a quotation can tell it is
    # looking at a preprint without having to parse prose. `source` above
    # is still the URL that was requested; `oa_url` is where the body came
    # from. See core/oa.py.
    if "oa_url" not in row.keys() or not row["oa_url"]:
        return
    kind = row["oa_recovery_kind"] if "oa_recovery_kind" in row.keys() else None
    data["oa"] = {
        "url": row["oa_url"],
        "resolver": row["oa_source"],
        "version": row["oa_version"],
        "license": row["oa_license"],
        "body_is_not_from_source": True,
        # "rescued" is the stronger claim: the source URL was never
        # read, so the title and authors are the open-access copy's
        # too. "substituted" means only the body was replaced.
        "kind": kind,
        "nothing_from_source": kind == "rescued",
    }


def _attach_note_body(data: dict, row) -> None:
    body = row["body"]
    from hyperresearch.core.untrusted import is_untrusted, wrap_body

    if is_untrusted(data.get("source"), data.get("type")):
        data["body"] = wrap_body(body, data["source"])
        data["untrusted"] = True
    else:
        data["body"] = body


def _fetch_note_data(vault, nid: str, meta: bool) -> dict | None:
    row = vault.db.execute(
        "SELECT n.*, nc.body FROM notes n JOIN note_content nc ON n.id = nc.note_id WHERE n.id = ?",
        (nid,),
    ).fetchone()
    if not row:
        return None
    tag_list = vault.db.execute(
        "SELECT GROUP_CONCAT(tag, ',') as tl FROM tags WHERE note_id = ?", (nid,)
    ).fetchone()
    tags = tag_list["tl"].split(",") if tag_list and tag_list["tl"] else []
    data = {
        "id": row["id"],
        "title": row["title"],
        "path": row["path"],
        "status": row["status"],
        "type": row["type"],
        "tags": tags,
        # sqlite3.Row.__contains__ is broken (returns False even for present keys),
        # so use row.keys() explicitly. SIM118 + SIM401 are noqa'd accordingly.
        "tier": row["tier"] if "tier" in row.keys() else None,
        "content_type": row["content_type"] if "content_type" in row.keys() else None,
        "created": row["created"],
        "updated": row["updated"],
        "word_count": row["word_count"],
        "source": row["source"],
        "parent": row["parent"],
        "summary": row["summary"],
    }
    _attach_oa_info(row, data)
    if not meta:
        _attach_note_body(data, row)
    return data


def _print_raw_note(vault, note_id: str, json_output: bool) -> None:
    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        _note_not_found(note_id, json_output, "Note not found")
    console.print((vault.root / row["path"]).read_text(encoding="utf-8"))


def _print_note_meta(data: dict) -> None:
    for k, v in data.items():
        if v is not None:
            console.print(f"  [dim]{k}:[/] {v}")


def _print_note_body(data: dict) -> None:
    tags = data.get("tags", [])
    console.print(f"[bold]{data['title']}[/]  [dim]({data['id']})[/]")
    console.print(f"[dim]Status: {data['status']} | Tags: {', '.join(tags)}[/]")
    console.print()
    from rich.markdown import Markdown

    console.print(Markdown(data.get("body", "")))


def _print_note_data(data: dict, meta: bool, vault, json_output: bool) -> None:
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
        return
    if meta:
        _print_note_meta(data)
    else:
        _print_note_body(data)


def _show_single_note(vault, note_id: str, raw: bool, meta: bool, json_output: bool) -> None:
    # Single note — original behavior
    if raw:
        _print_raw_note(vault, note_id, json_output)
        return
    data = _fetch_note_data(vault, note_id, meta)
    if not data:
        _note_not_found(note_id, json_output, "Note not found")
    _print_note_data(data, meta, vault, json_output)


def _print_batch_notes(notes: list, meta: bool) -> None:
    for data in notes:
        tags = data.get("tags", [])
        console.print(f"\n[bold]{data['title']}[/]  [dim]({data['id']})[/]")
        console.print(f"[dim]Status: {data['status']} | Tags: {', '.join(tags)}[/]")
        if not meta:
            console.print()
            from rich.markdown import Markdown

            console.print(Markdown(data.get("body", "")))


def _show_note_batch(vault, note_ids: list, meta: bool, json_output: bool) -> None:
    # Multi-note — batch read
    notes = []
    not_found = []
    for nid in note_ids:
        data = _fetch_note_data(vault, nid, meta)
        if data:
            notes.append(data)
        else:
            not_found.append(nid)
    if json_output:
        result = {"notes": notes, "not_found": not_found}
        output(success(result, count=len(notes), vault=str(vault.root)), json_mode=True)
        return
    _print_batch_notes(notes, meta)
    if not_found:
        console.print(f"\n[red]Not found:[/] {', '.join(not_found)}")


@app.command("show")
def note_show(
    note_ids: list[str] = typer.Argument(
        ..., help="Note ID(s) — pass multiple to read several at once"
    ),
    raw: bool = typer.Option(False, "--raw", "-r", help="Show raw markdown"),
    meta: bool = typer.Option(False, "--meta", "-m", help="Show only frontmatter"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Display one or more notes. Pass multiple IDs for batch read."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    if len(note_ids) == 1:
        _show_single_note(vault, note_ids[0], raw, meta, json_output)
        return
    _show_note_batch(vault, note_ids, meta, json_output)


def _build_list_filters(tag, fields: dict) -> tuple:
    clauses: list = []
    params: list = []
    for key, clause in _LIST_FILTERS:
        value = fields.get(key)
        if value:
            clauses.append(clause)
            params.append(value)
    for t in tag or []:
        clauses.append("n.id IN (SELECT note_id FROM tags WHERE tag = ?)")
        params.append(t.lower())
    return clauses, params


def _fetch_note_list(vault, clauses: list, params: list, order: str, effective_limit: int) -> list:
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = vault.db.execute(
        f"""SELECT n.*,
            (SELECT GROUP_CONCAT(t.tag, ',') FROM tags t WHERE t.note_id = n.id) as tag_list
        FROM notes n WHERE {where} ORDER BY {order} LIMIT ?""",
        [*params, effective_limit],
    ).fetchall()
    notes = []
    for row in rows:
        tag_list = row["tag_list"].split(",") if row["tag_list"] else []
        notes.append(
            {
                "id": row["id"],
                "title": row["title"],
                "path": row["path"],
                "status": row["status"],
                "type": row["type"],
                # sqlite3.Row.__contains__ is broken; row.keys() is reliable.
                "tier": row["tier"] if "tier" in row.keys() else None,
                "content_type": row["content_type"] if "content_type" in row.keys() else None,
                "tags": tag_list,
                "word_count": row["word_count"],
                "summary": row["summary"],
                "created": row["created"],
                "updated": row["updated"],
            }
        )
    return notes


def _report_note_list(vault, notes: list, json_output: bool) -> None:
    if json_output:
        output(
            success(notes, count=len(notes), vault=str(vault.root)),
            json_mode=True,
        )
    else:
        print_note_summary(notes)


@app.command("list")
def note_list(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    note_type: str | None = typer.Option(None, "--type", help="Filter by type"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Filter by tag (repeatable, AND logic)"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent"),
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
    sort: str = typer.Option("updated", "--sort", help="Sort: created|updated|title|words"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    all_notes: bool = typer.Option(False, "--all", "-a", help="Return all notes (no limit)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List notes with optional filters."""
    from hyperresearch.core.vault import Vault
    from hyperresearch.models.note import ContentType, Tier

    # Validate enums up-front
    _validate_note_enum(tier, Tier, "--tier", "INVALID_TIER", json_output)
    _validate_note_enum(
        content_type, ContentType, "--content-type", "INVALID_CONTENT_TYPE", json_output
    )

    vault = Vault.discover()
    vault.auto_sync()

    clauses, params = _build_list_filters(
        tag,
        {
            "status": status,
            "note_type": note_type,
            "parent": parent,
            "tier": tier,
            "content_type": content_type,
        },
    )

    sort_map = {
        "created": "n.created DESC",
        "updated": "COALESCE(n.updated, n.created) DESC",
        "title": "n.title ASC",
        "words": "n.word_count DESC",
    }
    order = sort_map.get(sort, "COALESCE(n.updated, n.created) DESC")

    effective_limit = 999999 if all_notes else limit
    notes = _fetch_note_list(vault, clauses, params, order, effective_limit)
    _report_note_list(vault, notes, json_output)


@app.command("edit")
def note_edit(
    note_id: str = typer.Argument(..., help="Note ID to edit"),
) -> None:
    """Open a note in $EDITOR."""
    import os
    import subprocess

    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        console.print(f"[red]Not found:[/] {note_id}")
        raise typer.Exit(1)

    file_path = vault.root / row["path"]
    editor = os.environ.get(
        "EDITOR", os.environ.get("VISUAL", "notepad" if os.name == "nt" else "vim")
    )
    subprocess.run([editor, str(file_path)])


def _apply_status(meta, set_status, changed: list) -> None:
    if not set_status:
        return
    from hyperresearch.models.note import NoteStatus

    meta.status = NoteStatus(set_status)
    changed.append(f"status={set_status}")


def _apply_tag_changes(meta, add_tag: list, remove_tag: list, changed: list) -> None:
    for t in add_tag:
        if t.lower() not in meta.tags:
            meta.tags.append(t.lower())
            changed.append(f"+tag:{t}")
    for t in remove_tag:
        if t.lower() in meta.tags:
            meta.tags.remove(t.lower())
            changed.append(f"-tag:{t}")


def _apply_scalar_fields(
    meta,
    set_summary,
    set_parent,
    set_source,
    set_tier,
    set_content_type,
    deprecate: bool,
    changed: list,
) -> None:
    from hyperresearch.models.note import ContentType, NoteStatus, Tier

    if set_summary is not None:
        meta.summary = set_summary
        changed.append("summary")
    if set_parent is not None:
        meta.parent = set_parent
        changed.append(f"parent={set_parent}")
    if set_source is not None:
        meta.source = set_source
        changed.append("source")
    if set_tier is not None:
        meta.tier = Tier(set_tier)
        changed.append(f"tier={set_tier}")
    if set_content_type is not None:
        meta.content_type = ContentType(set_content_type)
        changed.append(f"content_type={set_content_type}")
    if deprecate:
        meta.deprecated = True
        meta.status = NoteStatus("deprecated")
        changed.append("deprecated")


def _apply_note_updates(
    meta,
    set_status,
    add_tag: list,
    remove_tag: list,
    set_summary,
    set_parent,
    set_source,
    set_tier,
    set_content_type,
    deprecate: bool,
) -> list:
    changed = []
    _apply_status(meta, set_status, changed)
    _apply_tag_changes(meta, add_tag, remove_tag, changed)
    _apply_scalar_fields(
        meta, set_summary, set_parent, set_source, set_tier, set_content_type, deprecate, changed
    )
    return changed


def _report_no_changes(note_id: str, vault, json_output: bool) -> None:
    if json_output:
        output(success({"id": note_id, "changed": []}, vault=str(vault.root)), json_mode=True)
    else:
        console.print("[dim]Nothing to update.[/]")


def _save_updated_note(vault, file_path, meta, body) -> None:
    from datetime import datetime

    from hyperresearch.core.frontmatter import serialize_frontmatter

    meta.updated = datetime.now(UTC)
    file_path.write_text(serialize_frontmatter(meta) + "\n" + body, encoding="utf-8")
    _sync_notes(vault)


def _report_note_updated(note_id: str, changed: list, vault, json_output: bool) -> None:
    if json_output:
        output(success({"id": note_id, "changed": changed}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Updated {note_id}:[/] {', '.join(changed)}")


@app.command("update")
def note_update(
    note_id: str = typer.Argument(..., help="Note ID"),
    set_status: str | None = typer.Option(None, "--status", "-s", help="Set status"),
    add_tag: list[str] = typer.Option([], "--add-tag", help="Add tag(s)"),
    remove_tag: list[str] = typer.Option([], "--remove-tag", help="Remove tag(s)"),
    set_summary: str | None = typer.Option(None, "--summary", help="Set summary"),
    set_parent: str | None = typer.Option(None, "--parent", "-p", help="Set parent topic"),
    set_source: str | None = typer.Option(None, "--source", help="Set source URL/path"),
    set_tier: str | None = typer.Option(
        None,
        "--tier",
        help="Set epistemic tier: ground_truth|institutional|practitioner|commentary|unknown",
    ),
    set_content_type: str | None = typer.Option(
        None,
        "--content-type",
        help="Set artifact kind: paper|docs|article|blog|forum|dataset|policy|code|book|transcript|review|unknown",
    ),
    deprecate: bool = typer.Option(False, "--deprecate", help="Mark as deprecated"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Update frontmatter fields on a single note."""
    from hyperresearch.core.frontmatter import parse_frontmatter
    from hyperresearch.core.vault import Vault
    from hyperresearch.models.note import ContentType, NoteStatus, Tier

    # Validate enums up-front
    _validate_note_enum(set_status, NoteStatus, "--status", "INVALID_STATUS", json_output)
    _validate_note_enum(set_tier, Tier, "--tier", "INVALID_TIER", json_output)
    _validate_note_enum(
        set_content_type, ContentType, "--content-type", "INVALID_CONTENT_TYPE", json_output
    )

    vault = Vault.discover()
    vault.auto_sync()

    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        _note_not_found(note_id, json_output)

    file_path = vault.root / row["path"]
    content = file_path.read_text(encoding="utf-8-sig")
    meta, body = parse_frontmatter(content)

    changed = _apply_note_updates(
        meta,
        set_status,
        add_tag,
        remove_tag,
        set_summary,
        set_parent,
        set_source,
        set_tier,
        set_content_type,
        deprecate,
    )
    if not changed:
        _report_no_changes(note_id, vault, json_output)
        return

    _save_updated_note(vault, file_path, meta, body)
    _report_note_updated(note_id, changed, vault, json_output)


@app.command("mv")
def note_mv(
    note_id: str = typer.Argument(..., help="Note ID to move"),
    new_path: str = typer.Argument(..., help="New relative path (e.g. notes/python/renamed.md)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Move/rename a note, updating all references."""
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        if json_output:
            output(error(f"Note not found: {note_id}", "NOT_FOUND"), json_mode=True)
        else:
            console.print(f"[red]Not found:[/] {note_id}")
        raise typer.Exit(1)

    old_file = vault.root / row["path"]
    new_file = vault.root / new_path

    new_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.rename(new_file)

    # Re-sync
    plan = compute_sync_plan(vault, force=True)
    execute_sync(vault, plan)

    if json_output:
        output(
            success({"old_path": row["path"], "new_path": new_path}, vault=str(vault.root)),
            json_mode=True,
        )
    else:
        console.print(f"[green]Moved:[/] {row['path']} → {new_path}")


def _remove_raw_file(vault, file_path):
    """Unlink the raw file from frontmatter. Returns its vault-relative path or None."""
    # Read raw_file straight from the markdown frontmatter — the DB row
    # may not carry that field if the schema was synced before the column
    # existed. File parsing is authoritative.
    if not file_path.exists():
        return None
    try:
        from hyperresearch.core.frontmatter import parse_frontmatter

        meta, _ = parse_frontmatter(file_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not meta.raw_file:
        return None
    # Resolve and guard against path traversal — a malicious or
    # corrupted frontmatter could set raw_file to "../../etc/passwd".
    # Refuse to unlink anything outside <vault>/research/.
    research_root = (vault.research_dir).resolve()
    raw_path = (vault.research_dir / meta.raw_file).resolve()
    try:
        raw_path.relative_to(research_root)
    except ValueError:
        return None
    if raw_path.exists() and raw_path.is_file():
        raw_path.unlink()
        return str(raw_path.relative_to(vault.root).as_posix())
    return None


def _remove_assets_dir(vault, note_id: str) -> list:
    removed = []
    assets_dir = vault.research_dir / "assets" / note_id
    if assets_dir.exists() and assets_dir.is_dir():
        import shutil

        for asset_file in assets_dir.iterdir():
            if asset_file.is_file():
                removed.append(asset_file.name)
        shutil.rmtree(assets_dir, ignore_errors=True)
    return removed


def _report_note_deleted(
    note_id: str, removed_raw, removed_assets: list, vault, json_output: bool
) -> None:
    payload: dict = {"deleted": note_id}
    if removed_raw:
        payload["removed_raw"] = removed_raw
    if removed_assets:
        payload["removed_assets"] = removed_assets
    if json_output:
        output(success(payload, vault=str(vault.root)), json_mode=True)
        return
    msg = f"[red]Deleted:[/] {note_id}"
    if removed_raw:
        msg += f"\n  raw: {removed_raw}"
    if removed_assets:
        msg += f"\n  assets: {len(removed_assets)} file(s)"
    console.print(msg)


@app.command("rm")
def note_rm(
    note_id: str = typer.Argument(..., help="Note ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Delete a note and its associated raw file and assets.

    Previous versions only unlinked the `.md` file, leaving raw PDFs under
    `output/raw/` and assets under `output/assets/<id>/` as orphans.
    Every fetch-then-delete cycle leaked disk. The current implementation
    also removes:
      - the raw file referenced in the note's `raw_file` frontmatter field
      - any entries in the `assets` table and their files on disk
    """
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        _note_not_found(note_id, json_output)

    file_path = vault.root / row["path"]
    if not force and not json_output:
        typer.confirm(f"Delete {row['path']}?", abort=True)

    removed_raw = _remove_raw_file(vault, file_path)
    removed_assets = _remove_assets_dir(vault, note_id)

    # Finally, unlink the .md file, then re-sync to update DB
    if file_path.exists():
        file_path.unlink()
    _sync_notes(vault)

    _report_note_deleted(note_id, removed_raw, removed_assets, vault, json_output)
