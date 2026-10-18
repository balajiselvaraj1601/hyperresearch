"""Watch mode — auto-sync on file changes."""

from __future__ import annotations

import time

import typer

from hyperresearch.cli._output import console


def _import_watchdog():
    try:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        console.print("[red]Watch mode requires: pip install hyperresearch[watch][/]")
        raise typer.Exit(1)
    return FileSystemEvent, FileSystemEventHandler, Observer


def _handle_fs_event(handler, event) -> None:
    if not event.src_path.endswith(".md"):  # type: ignore[arg-type]
        return
    if ".hyperresearch" in str(event.src_path):
        return
    handler._pending = True
    handler._last_event = time.monotonic()


def _check_and_maybe_sync(handler) -> bool:
    if not handler._pending:
        return False
    # Debounce: wait 500ms after last event
    if time.monotonic() - handler._last_event < 0.5:
        return False
    handler._pending = False
    return _sync_pending(handler._vault, handler._rebuild_index, handler._run_lint)


def _make_handler(base, vault, rebuild_index: bool, run_lint: bool):
    """Debounced watchdog handler subclassing the (optional) watchdog base."""

    class _Debounced(base):  # type: ignore[valid-type, misc]
        def __init__(self):
            super().__init__()
            self._vault = vault
            self._rebuild_index = rebuild_index
            self._run_lint = run_lint
            self._pending = False
            self._last_event = 0.0

        def on_any_event(self, event):
            _handle_fs_event(self, event)

        def check_and_sync(self):
            return _check_and_maybe_sync(self)

    return _Debounced()


def _rebuild_watch_indexes(vault) -> None:
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.indexgen.generator import IndexGenerator

    gen = IndexGenerator(vault)
    built = gen.build_all()
    # Re-sync to index the index pages
    plan2 = compute_sync_plan(vault)
    if plan2.to_add or plan2.to_update:
        execute_sync(vault, plan2)
    console.print(f"  [dim]Rebuilt {len(built)} indexes[/]")


def _sync_pending(vault, rebuild_index: bool, run_lint: bool) -> bool:
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    try:
        plan = compute_sync_plan(vault)
        if plan.to_add or plan.to_update or plan.to_delete:
            result = execute_sync(vault, plan)
            console.print(
                f"[green]Synced:[/] +{result.added} ~{result.updated} "
                f"-{result.deleted} ({result.duration_ms:.0f}ms)"
            )
            for err in result.errors:
                console.print(f"  [red]Error:[/] {err['path']}: {err['error']}")

            if rebuild_index:
                _rebuild_watch_indexes(vault)

            if run_lint:
                _quick_lint(vault)

            return True
    except Exception as e:
        console.print(f"[red]Sync error:[/] {e}")
    return False


def _observe_forever(handler, observer) -> None:
    try:
        while True:
            handler.check_and_sync()
            time.sleep(0.2)
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[dim]Stopped watching.[/]")
    observer.join()


def watch(
    rebuild_index: bool = typer.Option(
        False, "--rebuild-index", "-i", help="Rebuild indexes after sync"
    ),
    run_lint: bool = typer.Option(False, "--lint", "-l", help="Run lint after sync"),
) -> None:
    """Watch for file changes and auto-sync."""
    from hyperresearch.core.vault import Vault

    _, handler_base, observer_cls = _import_watchdog()
    vault = Vault.discover()
    console.print(f"[bold]Watching:[/] {vault.root}")
    console.print("[dim]Press Ctrl+C to stop.[/]\n")

    handler = _make_handler(handler_base, vault, rebuild_index, run_lint)
    observer = observer_cls()
    observer.schedule(handler, str(vault.research_dir), recursive=True)
    observer.start()
    _observe_forever(handler, observer)


def _quick_lint(vault) -> None:
    """Run a quick lint and print summary."""
    conn = vault.db
    broken = conn.execute("SELECT COUNT(*) as c FROM links WHERE target_id IS NULL").fetchone()["c"]
    orphans = conn.execute("""
        SELECT COUNT(*) as c FROM notes n
        WHERE n.type NOT IN ('index', 'raw')
          AND n.id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)
          AND n.id NOT IN (SELECT DISTINCT source_id FROM links)
    """).fetchone()["c"]
    if broken or orphans:
        parts = []
        if broken:
            parts.append(f"{broken} broken links")
        if orphans:
            parts.append(f"{orphans} orphans")
        console.print(f"  [yellow]Lint: {', '.join(parts)}[/]")
