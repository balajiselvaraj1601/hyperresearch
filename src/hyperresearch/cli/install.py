"""Install command — one-step setup: vault init + agent hooks + docs injection."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def _resolve_default_profile(explicit: str | None, config_path: Path | None) -> str:
    # No explicit --profile → use the gear persisted by `hpr profile use`
    # in the target's config (falling back to "full").
    if explicit is not None:
        return explicit
    if config_path is not None and config_path.exists():
        from hyperresearch.core.config import VaultConfig

        return VaultConfig.load(config_path).pipeline_profile
    return "full"


def _check_profile(resolved: str, config_path: Path | None, json_output: bool) -> None:
    # Validate the profile early so a typo fails before any files are written.
    from hyperresearch.core.profiles import ProfileError, resolve_profile

    try:
        resolve_profile(resolved, config_path)
    except ProfileError as e:
        if json_output:
            output(error(str(e), "UNKNOWN_PROFILE"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _report_steps_retired(path: str, json_output: bool) -> None:
    if json_output:
        output(
            success(
                {
                    "steps_installed": None,
                    "target": str(Path(path).resolve()),
                    "notice": "Step skills retired; pipeline steps run via hyperresearch-runner agent",
                },
                vault=None,
            ),
            json_mode=True,
        )
    else:
        console.print(
            "[yellow]Notice:[/] Step skills are retired. Pipeline steps run via the external `hyperresearch-runner` agent."
        )


def _print_global_result(home: Path, hook_actions: list) -> None:
    console.print(f"[green]Global install:[/] {home}/.claude/")
    if hook_actions:
        for action in hook_actions:
            console.print(f"  {action}")
    else:
        console.print("[dim]All skills and agents already installed.[/]")
    console.print("\n[bold]Ready.[/] /hyperresearch is now available in every Claude Code session.")
    console.print(
        "[dim]On first /hyperresearch run in a project, the vault, output/ folder, "
        "and the 16 step skills are created in that project's .claude/.[/]"
    )


def _install_global(profile: str | None, json_output: bool) -> None:
    from hyperresearch.core.agent_docs import _resolve_executable
    from hyperresearch.core.hooks import install_global_hooks

    hpr_path = _resolve_executable()
    home = Path.home()
    global_profile = profile if profile is not None else "full"
    _check_profile(global_profile, None, json_output)
    hook_actions = install_global_hooks(home, hpr_path=hpr_path, profile=global_profile)
    if json_output:
        output(
            success(
                {"global": True, "home": str(home), "hooks_installed": hook_actions},
                vault=None,
            ),
            json_mode=True,
        )
        return
    _print_global_result(home, hook_actions)


def _init_vault(root: Path, name: str, json_output: bool):
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.init(root, name=name), "created"
    except VaultError as e:
        if json_output:
            output(error(str(e), "INIT_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _open_or_init_vault(root: Path, name: str, json_output: bool):
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover(root), "existing"
    except VaultError:
        return _init_vault(root, name, json_output)


def _print_action_list(header: str, actions: list) -> None:
    if actions:
        console.print(header)
        for action in actions:
            console.print(f"  {action}")


def _print_crawl4ai_status(crawl4ai_status: str) -> None:
    if crawl4ai_status == "configured":
        console.print("[green]crawl4ai:[/] detected, set as default provider + browser ready")
    elif crawl4ai_status == "browser_installed":
        console.print("[green]crawl4ai:[/] browser installed + set as default provider")
    elif crawl4ai_status == "not_installed":
        console.print(
            "[dim]crawl4ai:[/] not installed. "
            "For local headless browsing: pip install hyperresearch[crawl4ai]"
        )


def _print_install_result(
    vault, vault_action: str, doc_actions: list, hook_actions: list, crawl4ai_status: str
) -> None:
    if vault_action == "created":
        console.print(f"[green]Vault created:[/] {vault.root}")
    else:
        console.print(f"[dim]Vault exists:[/] {vault.root}")
    _print_action_list("[green]Agent docs:[/]", doc_actions)
    _print_action_list("[green]Hooks installed:[/]", hook_actions)
    if not hook_actions:
        console.print("[dim]All hooks already installed.[/]")
    _print_crawl4ai_status(crawl4ai_status)
    console.print("\n[bold]Ready.[/] Agents will now check the research base before web searches.")
    console.print(
        "[dim]Tip: Run 'hyperresearch setup' for interactive configuration (profile, stealth, etc.)[/]"
    )


def install(
    path: str = typer.Argument(".", help="Path to install in"),
    name: str = typer.Option("Research Base", "--name", "-n", help="Vault name"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
    global_install: bool = typer.Option(
        False,
        "--global",
        "-g",
        help="Install Claude Code entry skill + agents to ~/.claude/ so /hyperresearch works in every Claude Code session anywhere. Skips vault init, CLAUDE.md, and step skills (retired as of v8; pipeline steps run via hyperresearch-runner agent).",
    ),
    steps_only: bool = typer.Option(
        False,
        "--steps-only",
        help="Step skills are retired as of v8. Pipeline steps run via the external `hyperresearch-runner` agent. This flag is kept for compatibility but does nothing.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Pipeline profile to render skill/agent prompts from (built-in gears: full, premier; plus any [profile.*] defined in .hyperresearch/config.toml). Defaults to the gear persisted by `hyperresearch profile use` (or 'full'). See `hyperresearch profile list`.",
    ),
) -> None:
    """Install hyperresearch: init vault + inject CLAUDE.md + install Claude Code hooks."""
    import sys

    from hyperresearch.core.hooks import install_hooks

    # Steps-only path: step skills are retired as of v8. Pipeline steps
    # run via the external `hyperresearch-runner` agent. This flag is kept
    # for compatibility but is a no-op.
    if steps_only:
        _report_steps_retired(path, json_output)
        return

    # Global install path: only the user-level Claude Code entry skill +
    # agents. No vault, no CLAUDE.md, no step skills — pure "make the
    # slash command available everywhere" mode. Step skills are retired as
    # of v8; pipeline steps run via the external `hyperresearch-runner`
    # agent.
    if global_install:
        _install_global(profile, json_output)
        return

    root = Path(path).resolve()

    # First-time install in an interactive terminal → run the setup TUI instead
    is_new = not (root / ".hyperresearch").exists()
    is_interactive = not json_output and sys.stdin.isatty()
    if is_new and is_interactive:
        from hyperresearch.cli.setup import setup

        setup(path=path, json_output=False)
        return

    vault, vault_action = _open_or_init_vault(root, name, json_output)

    from hyperresearch.core.agent_docs import _resolve_executable, inject_agent_docs

    hpr_path = _resolve_executable()
    doc_actions = inject_agent_docs(root)

    project_config = root / ".hyperresearch" / "config.toml"
    project_config_path = project_config if project_config.exists() else None
    project_profile = _resolve_default_profile(profile, project_config_path)
    _check_profile(project_profile, project_config_path, json_output)
    hook_actions = install_hooks(root, hpr_path=hpr_path, profile=project_profile)

    crawl4ai_status = _setup_crawl4ai(vault)

    data = {
        "vault_path": str(vault.root),
        "vault": vault_action,
        "agent_docs": doc_actions,
        "hooks_installed": hook_actions,
        "crawl4ai": crawl4ai_status,
    }

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        _print_install_result(vault, vault_action, doc_actions, hook_actions, crawl4ai_status)


def _setup_crawl4ai(vault) -> str:
    """Detect crawl4ai, install browser if needed, set as default provider.

    Returns: 'configured' (already ready), 'browser_installed' (just set up),
             'not_installed' (crawl4ai not available).
    """
    # find_spec, not an import: this only asks whether crawl4ai is installed,
    # and importing it is expensive.
    if importlib.util.find_spec("crawl4ai") is None:
        return "not_installed"

    if vault.config.web_provider == "builtin":
        vault.config.web_provider = "crawl4ai"
        vault.config.save(vault.config_path)

    # Check if the browser is already installed -- against the stack the
    # provider will actually launch: patchright (stealth adapter) pins its
    # own chromium build, so a passing plain-playwright check can mask a
    # missing patchright browser.
    try:
        try:
            from patchright.sync_api import sync_playwright
        except ImportError:
            from playwright.sync_api import sync_playwright  # type: ignore[assignment]

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
        return "configured"
    except Exception:
        pass

    # Try to install the browser. The stealth (patchright) adapter pins its
    # OWN chromium build with a separate registry -- `playwright install`
    # does not provide it, and the provider then dies at launch with a
    # missing-executable error. Install patchright's browser when patchright
    # is present; plain playwright is the fallback for non-stealth setups.
    import subprocess
    import sys

    installers = []
    if importlib.util.find_spec("patchright") is not None:
        installers.append("patchright")
    installers.append("playwright")
    for mod in installers:
        try:
            subprocess.run(
                [sys.executable, "-m", mod, "install", "chromium"],
                check=True,
                capture_output=True,
            )
            return "browser_installed"
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return "configured"  # best effort — user can install manually
