"""Golden tests: rendering the shipped templates with the `full` profile must
reproduce the pre-templating prompt content byte-for-byte.

The golden fixtures under tests/fixtures/golden_prompts/ were snapshotted from
the 1.x (pre-template) prompt sources. Any numeric drift between the built-in
profiles and the templates shows up here as a diff — changing a profile value
or template deliberately requires updating the golden, which makes prompt
changes reviewable instead of silent.

Deliberate deviations already folded into the goldens (2026-07-19):
  - Untrusted-source policy (2026-07-20): RESEARCHER_AGENT and
    DEPTH_INVESTIGATOR_AGENT gained the "Untrusted content policy" block
    (fetched note bodies arrive fenced in <untrusted-source> delimiters and
    must be treated as data, not instructions).
  - width-sweep: the three inconsistent full-tier source-target statements
    (40-100 / 40–80 / 55–80) were unified to the profile value 55–80; the
    light target 12–20 was unified to the table value 15–25; the tier table's
    full fetchers-per-wave 8–12 was unified to the Wave-1 value 10–12.
  - Phase-2 source-ranking additions (2026-07-19): width-sweep gained the
    utility-scores-travel-with-URLs rule and step 2.7 (persist ranking
    signals: claims ingest / backfill-doi / sources score / graph rank);
    triple-draft 10.2 gained ranked-curation via `search --ranked`; the
    fetcher agent gained the `--utility-score` pass-through section.
  - Phase-3 per-run workspaces (2026-07-19): every run-scoped artifact path
    moved from flat output/ to output/runs/<vault_tag>/ (query file is
    now runs/<tag>/query.md) across ALL skills and agent prompts; the router
    gained bootstrap step 2.5 (`hpr run init`), manifest-first recovery, and
    the dissertation tier row + step 1.5 (chapter partition).
  - Phase-4 browser lane (2026-07-19): width-sweep gained step 2.8 (drain
    the escalation queue via ONE browser-fetcher; consolidated needs_human
    prompt; run block --on human-challenges for non-interactive runs); the
    router gained the "Browser-lane escalations" section; new
    BROWSER_FETCHER_AGENT golden.
  - Phase-5 verification (2026-07-19): router tier sequences gained step
    14.5 (cite-check) and the final gate gained `run verify`, the
    retraction sweep, and the three verification lint rules; new
    CITE_CHECKER_AGENT golden.
  - Scale gears (2026-07-19): the router gained the "Scale gear (tier ≠
    gear)" section (full vs premier, `profile use`), premier in the run-init
    profile list, and a gear-aware frontmatter description; width-sweep's
    diminishing-returns note now cites the gear ceiling instead of the
    hardcoded "~65 reference / beyond ~80" full-scale prose. The `full.*`
    template refs that meant "the installed scale" became `p.*` — byte-
    identical under the default gear (verified by these goldens), truthful
    under `premier`.
  - ModelMap wiring + dollar-cost removal (2026-07-19): every agent's
    `model:` frontmatter line became `<< p.models.X >>` (rendered from the
    profile's ModelMap — same values under `full`, but now overridable, e.g.
    a haiku fetcher); "Runs on Sonnet/Opus" claims left descriptions and
    prose so a model override can't be contradicted by stale text; dollar
    figures were removed repo-wide (the router tier table lost its cost
    column, gap-fetch's "+$1-3 per run" became fetcher-count overhead
    framing, the source-analyst's "$2-5 per spawn" block became "Effort
    discipline", and its Sonnet-1M context claims became model-neutral).
  - Ship-gate enforcement (2026-07-19, after bench Q62 shipped a 25.6K-word
    report with 24 hallucinated-quote lint errors "assessed as false
    positives"): the router's final gate now centers on `run finish` (verify
    + manifest flip, no-override language, bounded fix loop) instead of the
    advisory verify+lint checklist, and invariant 14 makes `passed: true`
    the only definition of complete.
  - Report register + calm citations (2026-07-20, after the Q62 four-report
    comparison showed the judge's only consistent losses were pedagogy and
    readability): the instruction critic gained check R5 (section primers)
    and R2 now counts grouped citation markers (`[7, 12]` = two citations).
    The synthesizer and polish auditor (not golden-covered) gained the
    primer requirement, the calm citation style (grouped brackets, sentence-
    end placement, run consolidation with number-bearing anchors kept), and
    register discipline (meta-discourse ban, hedging discipline, kicker
    rationing) distilled from the humanize-ai-text skill.
  - Run levers (2026-07-20): step 1 now auto-selects register / domain
    notes / inference depth and renders them to shim files via `hpr levers
    render`; the router's spawn contract gained item 4 (paste the role's
    shim verbatim) and invariant 15; every spawning skill's spawn template
    gained a RUN DIRECTIVES paste line (output/drafting/critics/polish
    roles); every shim-receiving agent gained a Run-directives acceptance
    paragraph; the dialectic and instruction critics gained
    register-conditional standards. The cite-checker and
    9-evidence-digest are deliberately untouched (no shim: verification
    is register-independent; step 9 spawns nothing).
  - Coverage before elegance (2026-07-22, after the Q52 rerun scored below
    baseline on comprehensiveness and insight by trading the systematic
    comparison surface and a developed factor decomposition for a cleaner
    thesis, at the same word count): the depth critic gained a shallow-spot
    bullet for developed quantitative mechanisms compressed to a bare mention
    (the highest-insight loss), and the instruction critic gained check R6
    (comparison-axis coverage, register-independent). The synthesizer (not
    golden-covered) gained pass-1 item 12 (coverage and mechanism depth are
    load-bearing content), a reframed selectivity paragraph (select sources,
    not points), and a "never cut a point to hit the ceiling" clause.
  - Profile constants authored once (2026-09-11, #101): step 4 and the
    loci-analyst agent became generic over `p.loci_analysts` / `p.loci_max`
    ("both Task calls", `loci-a.json`/`loci-b.json`, "exceeds 6" were
    hardcoded next to the templated count and broke on premier's 3
    analysts); triple-draft's CJK char column now renders
    `p.char_targets_no_word_boundary` (argumentative 20000–25000 became
    15000–30000, the 3-chars-per-word ratio every other format already
    used); the instruction critic's density trigger, the synthesizer's
    citation totals + floor, the draft orchestrator's word targets, and
    the width-sweep utility-scoring gate + vault-check interval all render
    from the profile — byte-identical under `full`.
  - Script-neutral citation density (2026-09-11, #76): the instruction
    critic's R2 (and the synthesizer, not golden-covered) count words —
    characters / `p.chars_per_word_no_word_boundary` for scripts without
    word boundaries — against `p.citation_density_min` per 1000 WORDS (9,
    the old 1.5-per-1000-characters floor expressed in English words)
    instead of per 1000 characters.
  - Mimo-worker fetcher caps (2026-09-16, mimo-workers branch): RESEARCHER_AGENT
    per-source claims caps halved (short 2-4 / medium 4-8 / long 8-12, was
    3-8 / 8-15 / 15-25) and gained an "Output discipline (small-model workers)"
    block (digest returns, verbatim IDs, stop-at-cap). Chase/wave/model numbers
    stay profile-driven via the [profile.mimo] overlay — no template change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hyperresearch.core import hooks
from hyperresearch.core.hooks import _read_skill_source
from hyperresearch.core.render import build_render_context, render_prompt

GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "golden_prompts"

GOLDEN_SKILLS = [
    "hyperresearch",
    "hyperresearch-2-width-sweep",
    "hyperresearch-4-loci-analysis",
    "hyperresearch-5-depth-investigation",
    "hyperresearch-9-evidence-digest",
    "hyperresearch-10-triple-draft",
    "hyperresearch-13-gap-fetch",
    "hyperresearch-16-readability-audit",
]

@pytest.fixture(scope="module")
def ctx():
    return build_render_context(None, primary="full")


@pytest.mark.parametrize("skill_name", GOLDEN_SKILLS)
def test_skill_render_matches_golden(skill_name, ctx):
    template = _read_skill_source(f"{skill_name}.md")
    assert template is not None, f"missing skill source {skill_name}.md"
    rendered = render_prompt(template, ctx)
    golden = (GOLDEN_DIR / "skills" / f"{skill_name}.md").read_text(encoding="utf-8")
    assert rendered == golden, (
        f"render(full) of {skill_name}.md deviates from golden. If the change "
        "is deliberate, update tests/fixtures/golden_prompts/skills/ and note "
        "it in the module docstring."
    )




@pytest.mark.parametrize("skill_name", GOLDEN_SKILLS)
def test_no_unrendered_variables_in_skills(skill_name, ctx):
    rendered = render_prompt(_read_skill_source(f"{skill_name}.md"), ctx)
    assert "<<" not in rendered and ">>" not in rendered


def test_profile_override_changes_render(tmp_path):
    """End-to-end: a profile overlay must actually change the rendered skill."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("[profile.full]\nsource_min = 200\n", encoding="utf-8")
    ctx = build_render_context(cfg, primary="full")
    rendered = render_prompt(_read_skill_source("hyperresearch-2-width-sweep.md"), ctx)
    assert "| `full` | 200 |" in rendered


@pytest.mark.parametrize("skill_name", GOLDEN_SKILLS)
def test_premier_gear_renders_cleanly(skill_name):
    """Every golden-covered skill must render without holes at premier gear,
    and the scale-bearing ones must carry premier numbers."""
    ctx = build_render_context(None, primary="premier")
    rendered = render_prompt(_read_skill_source(f"{skill_name}.md"), ctx)
    assert "<<" not in rendered and ">>" not in rendered
    if skill_name == "hyperresearch-2-width-sweep":
        assert "| `full` | 90 | 100–130 |" in rendered
        assert "beyond ~130 sources" in rendered
        # The light tier row is gear-independent
        assert "| `light` | 10 | 15–25 |" in rendered
    if skill_name == "hyperresearch":
        assert "currently `premier`" in rendered
        assert "~3–5 hours" in rendered
        # The step table's counts follow the gear (premier: 3 loci-analysts).
        assert "| 3 loci-analysts → scored loci.json" in rendered
    if skill_name == "hyperresearch-4-loci-analysis":
        # premier spawns 3 analysts and clamps to 10 loci; nothing in the
        # prose may still assume two analysts or six loci (#101).
        assert "Spawns 3 parallel loci-analyst" in rendered
        assert "Wait for all 3." in rendered
        assert "clamp to 10." in rendered
        assert "exceeds 10," in rendered
        for stale in (
            "both Task calls", "Wait for both", "both analysts", "Read both",
            "loci-a.json", "loci-b.json", "instance A or B", "exceeds 6",
        ):
            assert stale not in rendered, stale
    if skill_name == "hyperresearch-10-triple-draft":
        # premier word targets carry their own CJK char targets (3:1).
        assert "8000–16000 words / 24000–48000 chars (CJK)" in rendered




def test_install_writes_rendered_prompts_with_header(tmp_vault):
    """install_hooks renders templates and stamps the provenance header.
    As of v8, the agent fleet and step skills are retired; only the hook
    and entry skill are installed."""
    from hyperresearch.core.hooks import install_hooks

    install_hooks(tmp_vault.root, hpr_path="hyperresearch")

    # No agents should be installed (fleet retired)
    agents_dir = tmp_vault.root / ".claude" / "agents"
    if agents_dir.exists():
        actual_agents = {p.name for p in agents_dir.iterdir() if p.is_file()}
        assert actual_agents == set(), f"Unexpected agent files: {actual_agents}"

    # Step skills should not be installed
    skills_dir = tmp_vault.root / ".claude" / "skills"
    if skills_dir.exists():
        for child in skills_dir.iterdir():
            if child.is_dir() and child.name.startswith("hyperresearch-") and child.name != "hyperresearch":
                assert False, f"Unexpected step skill directory: {child}"

    # Entry skill retired too — no router SKILL.md is written
    assert not (tmp_vault.root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").exists()

    # Hook settings written
    assert (tmp_vault.root / ".claude" / "settings.json").exists()
    assert (tmp_vault.root / ".hyperresearch" / "hook.js").exists()


def test_install_with_profile_overlay(tmp_vault):
    """A vault-config profile overlay flows into installed prompts.
    As of v8, step skills are retired; the entry skill still receives the overlay."""
    from hyperresearch.core.hooks import install_hooks

    cfg_path = tmp_vault.config_path
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "\n[profile.full]\nsource_min = 200\n",
        encoding="utf-8",
    )
    install_hooks(tmp_vault.root, hpr_path="hyperresearch")

    # Nothing skill-shaped is installed any more (entry skill + step skills retired),
    # so assert the overlay against the renderer directly rather than a written file.
    from hyperresearch.core.hooks import _read_skill_source, _render_installed, _set_render_state

    _set_render_state("full", cfg_path)
    source = _read_skill_source("hyperresearch.md")
    assert source is not None, "step-contract source must still ship in the package"
    rendered = _render_installed(source)
    assert "200" in rendered, "profile overlay source_min=200 must reach the rendered contract"


# ---------------------------------------------------------------------------
# ModelMap wiring — the profile's per-agent model assignments must actually
# reach the installed agent frontmatter (they were decorative before 2.0).
# ---------------------------------------------------------------------------



def test_no_hardcoded_model_lines_in_agent_templates():
    """Every `model:` frontmatter line in the hooks.py agent constants must be
    a template ref (`model: << p.models.X >>`), never a literal model name —
    a literal would silently ignore the profile's ModelMap."""
    source = Path(hooks.__file__).read_text(encoding="utf-8")
    bad = [
        line.strip()
        for line in source.splitlines()
        if line.startswith("model: ") and not line.startswith("model: <<")
    ]
    assert not bad, f"hardcoded model lines in hooks.py: {bad}"


# ---------------------------------------------------------------------------
# No-contradiction sweep — rendered prompts must not carry dollar-cost ranges
# (not a bill on subscription billing) or hardcoded model-name claims that a
# ModelMap override would falsify.
# ---------------------------------------------------------------------------

_DOLLAR_RANGE = re.compile(r"\$\d+\s*[-–—]\s*\d+")
_MODEL_CLAIM = re.compile(r"[Rr]uns on (Sonnet|Opus|Haiku)")


def _all_skill_names() -> list[str]:
    import hyperresearch

    skills_dir = Path(hyperresearch.__file__).parent / "skills"
    return sorted(p.name for p in skills_dir.glob("*.md"))




@pytest.mark.parametrize("skill_file", _all_skill_names())
def test_rendered_skills_have_no_cost_or_model_claims(skill_file, ctx):
    rendered = render_prompt(_read_skill_source(skill_file), ctx)
    assert not _DOLLAR_RANGE.search(rendered), f"dollar-cost range in {skill_file}"
    assert not _MODEL_CLAIM.search(rendered), f"hardcoded model claim in {skill_file}"




# ---------------------------------------------------------------------------
# Lever shims: every spawning skill pastes its role's shim file; the
# cite-checker gets none (verification is register-independent).
# ---------------------------------------------------------------------------

_SKILL_SHIM_ROLES = {
    "hyperresearch-2-width-sweep": "research",
    "hyperresearch-4-loci-analysis": "research",
    "hyperresearch-5-depth-investigation": "research",
    "hyperresearch-8-corpus-critic": "research",
    "hyperresearch-13-gap-fetch": "research",
    "hyperresearch-10-triple-draft": "drafting",
    "hyperresearch-11-synthesize": "drafting",
    "hyperresearch-12-critics": "critics",
    "hyperresearch-14-patcher": "critics",
    "hyperresearch-15-polish": "polish",
    "hyperresearch-16-readability-audit": "polish",
}


@pytest.mark.parametrize("skill_name,role", sorted(_SKILL_SHIM_ROLES.items()))
def test_spawning_skills_carry_their_shim_paste_line(skill_name, role, ctx):
    rendered = render_prompt(_read_skill_source(f"{skill_name}.md"), ctx)
    assert f"shims/{role}.md" in rendered, (
        f"{skill_name} spawn template lost its shims/{role}.md paste line"
    )


def test_cite_check_skill_gets_no_shim(ctx):
    rendered = render_prompt(
        _read_skill_source("hyperresearch-14-5-cite-check.md"), ctx
    )
    assert "shims/" not in rendered


# ---------------------------------------------------------------------------
# Coverage before elegance: the synthesizer and the depth/instruction critics
# must carry the anti-compression guards so a rerun can't silently regress into
# trading substance for prose (see the 2026-07-22 deviation-log entry).
# ---------------------------------------------------------------------------


