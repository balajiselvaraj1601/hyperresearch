"""Profile commands — inspect, validate, and switch pipeline profiles.

Two distinct concepts, one command group:

- **Tiers** are chosen per query at run time: `light` (auto-classified for
  bounded queries) and `dissertation` (opt-in chaptered mega-runs). The
  pipeline routes tiers itself.
- **The gear** is the scale profile whose numbers are rendered into the
  installed skill/agent prompts: `full` (standard) or `premier` (max
  width/depth), plus any user-defined `[profile.*]` overlay. Switch gears
  with `hpr profile use <name>` — it re-renders every installed prompt and
  persists the choice in `.hyperresearch/config.toml`.
"""

from __future__ import annotations

from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


def _discover_vault():
    """The enclosing vault, or None when outside one."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover()
    except VaultError:
        return None


def _config_path() -> Path | None:
    """Config path of the enclosing vault, or None when outside a vault.

    Profiles resolve fine without a vault — you just get the built-ins.
    """
    vault = _discover_vault()
    return vault.config_path if vault else None


def _resolve_profile_row(n: str, cfg, row: dict) -> None:
    from hyperresearch.core.profiles import ProfileError, resolve_profile

    try:
        p = resolve_profile(n, cfg)
        row.update(
            description=p.description,
            sources=list(p.source_target),
            time_estimate=p.time_estimate,
        )
    except ProfileError as e:
        row.update(description=f"INVALID: {e}", sources=None, time_estimate="")


def _collect_profile_rows(names: list, cfg, current_gear: str) -> list:
    from hyperresearch.core.profiles import BUILTIN_PROFILES, GEAR_PROFILES

    rows = []
    for n in names:
        row: dict = {
            "name": n,
            "builtin": n in BUILTIN_PROFILES,
            "kind": "gear" if (n in GEAR_PROFILES or n not in BUILTIN_PROFILES) else "tier",
            "current_gear": n == current_gear,
        }
        _resolve_profile_row(n, cfg, row)
        rows.append(row)
    return rows


def _print_profile_rows(rows: list) -> None:
    for r in rows:
        mark = " [green]*current gear[/]" if r["current_gear"] else ""
        kind = r["kind"] if r["builtin"] else "user-defined gear"
        console.print(f"  [cyan]{r['name']}[/] [dim]({kind})[/]{mark}")
        if r["description"]:
            console.print(f"    {r['description']}")
        if r["sources"]:
            console.print(
                f"    [dim]sources {r['sources'][0]}-{r['sources'][1]}  {r['time_estimate']}[/]"
            )
    console.print(
        "\n[dim]Tiers route per query (light auto, dissertation opt-in). "
        "Switch the scale gear with: hyperresearch profile use <full|premier>[/]"
    )


@app.command("list")
def profile_list(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List available pipeline profiles (built-in + user-defined)."""
    from hyperresearch.core.profiles import list_profiles

    vault = _discover_vault()
    cfg = vault.config_path if vault else None
    current_gear = vault.config.pipeline_profile if vault else "full"

    names = list_profiles(cfg)
    rows = _collect_profile_rows(names, cfg, current_gear)

    if json_output:
        output(
            success({"profiles": rows, "current_gear": current_gear}, count=len(rows)),
            json_mode=True,
        )
        return
    _print_profile_rows(rows)


def _reject_tier_as_gear(name: str, json_output: bool) -> None:
    if name not in ("light", "dissertation"):
        return
    msg = (
        f"'{name}' is a run-time tier, not a scale gear. "
        "light is auto-selected for bounded queries; dissertation runs are requested "
        "per query (or via `hyperresearch run init <tag> --profile dissertation`). "
        "Gears control the flat pipeline's scale: full, premier, or a custom [profile.*] overlay."
    )
    if json_output:
        output(error(msg, "TIER_NOT_GEAR"), json_mode=True)
    else:
        console.print(f"[red]Error:[/] {msg}")
    raise typer.Exit(1)


def _resolve_gear(name: str, vault, json_output: bool):
    from hyperresearch.core.profiles import ProfileError, resolve_profile

    try:
        return resolve_profile(name, vault.config_path)
    except ProfileError as e:
        if json_output:
            output(error(str(e), "UNKNOWN_PROFILE"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _print_gear_switched(name: str, profile, actions: list) -> None:
    console.print(f"[green]Gear switched:[/] [bold]{name}[/]")
    if profile.description:
        console.print(f"  {profile.description}")
    console.print(
        f"  [dim]sources {profile.source_target[0]}-{profile.source_target[1]}"
        f"  {profile.time_estimate}[/]"
    )
    if actions:
        console.print(f"  re-rendered {len(actions)} skill/agent file(s)")
    else:
        console.print("  [dim]all installed prompts already at this gear[/]")
    console.print(
        "[dim]Takes effect on the next /hyperresearch run. Revert with: hyperresearch profile use full[/]"
    )


@app.command("use")
def profile_use(
    name: str = typer.Argument(
        ..., help="Gear profile to switch to (full, premier, or a [profile.*] overlay)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Switch the pipeline scale gear: re-render installed skills/agents from this profile and persist it as the project default."""
    vault = _discover_vault()
    if vault is None:
        msg = "no vault here — run `hyperresearch install` first"
        if json_output:
            output(error(msg, "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {msg}")
        raise typer.Exit(1)

    _reject_tier_as_gear(name, json_output)
    profile = _resolve_gear(name, vault, json_output)

    # Persist the gear, then re-render every installed prompt from it.
    vault.config.pipeline_profile = name
    vault.config.save(vault.config_path)

    from hyperresearch.core.agent_docs import _resolve_executable
    from hyperresearch.core.hooks import install_hooks

    actions = install_hooks(vault.root, hpr_path=_resolve_executable(), profile=name)

    data = {
        "gear": name,
        "description": profile.description,
        "sources": list(profile.source_target),
        "time_estimate": profile.time_estimate,
        "rerendered": actions,
    }
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
        return
    _print_gear_switched(name, profile, actions)


@app.command("show")
def profile_show(
    name: str = typer.Argument(..., help="Profile name"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show a resolved profile (built-in defaults + user overlay)."""
    from hyperresearch.core.profiles import ProfileError, resolve_profile

    try:
        profile = resolve_profile(name, _config_path())
    except ProfileError as e:
        if json_output:
            output(error(str(e), "UNKNOWN_PROFILE"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    data = profile.model_dump()
    if json_output:
        output(success(data), json_mode=True)
    else:
        console.print(f"[bold]{profile.name}[/]")
        for key, value in data.items():
            if key == "name":
                continue
            console.print(f"  {key} = {value}")


def _validate_one_profile(n: str, cfg) -> tuple:
    from hyperresearch.core.profiles import ProfileError, resolve_profile

    try:
        resolve_profile(n, cfg)
        return {"name": n, "valid": True, "error": None}, True
    except ProfileError as e:
        return {"name": n, "valid": False, "error": str(e)}, False


def _report_validation(results: list, ok: bool, json_output: bool) -> None:
    if json_output:
        if ok:
            output(
                success({"profiles": results, "all_valid": True}, count=len(results)),
                json_mode=True,
            )
        else:
            bad = "; ".join(f"{r['name']}: {r['error']}" for r in results if not r["valid"])
            output(error(f"invalid profile(s) — {bad}", "INVALID_PROFILE"), json_mode=True)
        return
    for r in results:
        mark = "[green]ok[/]" if r["valid"] else f"[red]INVALID[/] — {r['error']}"
        console.print(f"  [cyan]{r['name']}[/]: {mark}")


@app.command("validate")
def profile_validate(
    name: str | None = typer.Argument(None, help="Profile name (default: validate all)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Validate profile definitions (built-ins + user overlays)."""
    from hyperresearch.core.profiles import list_profiles

    cfg = _config_path()
    names = [name] if name else list_profiles(cfg)
    results = []
    ok = True
    for n in names:
        result, valid = _validate_one_profile(n, cfg)
        results.append(result)
        ok = ok and valid

    _report_validation(results, ok, json_output)
    if not ok:
        raise typer.Exit(1)
