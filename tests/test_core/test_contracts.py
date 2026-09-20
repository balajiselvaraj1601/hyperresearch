"""`run contract`: step contracts and role briefs render for a live run.

Regression for the 2026-09-18 lanes, which read the raw Jinja templates and
handed subagents relative paths and an unresolved `$HPR`.
"""

from __future__ import annotations

import pytest

from hyperresearch.core.contracts import ContractError, list_roles, render_contract
from hyperresearch.core.runs import init_run

TAG = "topic-abc123"


@pytest.fixture
def run_vault(tmp_vault):
    init_run(tmp_vault, TAG, profile="full", query="What is X?")
    return tmp_vault


class TestStepContract:
    def test_profile_placeholders_resolve(self, run_vault):
        text = render_contract(run_vault, TAG, step="2", hpr_path="/bin/hpr")
        assert "<< " not in text
        assert ">>" not in text.replace("->", "")

    def test_hpr_and_tag_and_paths_resolve(self, run_vault):
        text = render_contract(run_vault, TAG, step="7", hpr_path="/bin/hpr")
        assert "$HPR" not in text
        assert "<vault_tag>" not in text
        run_dir = str(run_vault.run_dir(TAG))
        assert f"{run_dir}/temp/source-tensions.json" in text
        # no run-relative path survives
        assert "`output/runs/" not in text and " output/runs/" not in text
        assert "`output/reports/" not in text and " output/reports/" not in text

    def test_fractional_step(self, run_vault):
        text = render_contract(run_vault, TAG, step="14.5", hpr_path="/bin/hpr")
        assert "cite-check" in text

    def test_unknown_step(self, run_vault):
        with pytest.raises(ContractError):
            render_contract(run_vault, TAG, step="99")

    def test_missing_run(self, tmp_vault):
        with pytest.raises(ContractError):
            render_contract(tmp_vault, "nope-000000", step="1")

    def test_exactly_one_of_step_or_role(self, run_vault):
        with pytest.raises(ContractError):
            render_contract(run_vault, TAG)
        with pytest.raises(ContractError):
            render_contract(run_vault, TAG, step="1", role="fetcher")


EXPECTED_ROLES = {
    "fetcher",
    "browser-fetcher",
    "source-analyst",
    "loci-analyst",
    "depth-investigator",
    "corpus-critic",
    "draft-orchestrator",
    "synthesizer",
    "dialectic-critic",
    "depth-critic",
    "width-critic",
    "instruction-critic",
    "patcher",
    "cite-checker",
    "polish-auditor",
    "readability-recommender",
}


class TestRoleBrief:
    def test_all_roles_ship(self):
        assert set(list_roles()) == EXPECTED_ROLES

    @pytest.mark.parametrize("role", sorted(EXPECTED_ROLES))
    def test_every_role_renders_clean(self, run_vault, role):
        text = render_contract(run_vault, TAG, role=role, hpr_path="/bin/hpr")
        assert "<< " not in text
        assert "$HPR" not in text
        assert "<vault_tag>" not in text
        assert "research/runs/" not in text
        assert "never self-remediate destructively" in text

    def test_fetcher_brief_carries_claims_extraction(self, run_vault):
        """Zero claims files in both 2026-09-18 runs: the fetcher's claims
        step lived only in the retired agent body. It must be in the brief."""
        text = render_contract(run_vault, TAG, role="fetcher", hpr_path="/bin/hpr")
        assert "claims-<note-id>.json" in text
        assert "quoted_support" in text

    def test_every_spawn_site_names_a_shipped_role(self, run_vault):
        """Each ROLE BRIEF line in a step contract must point at a role that
        renders (the <critic-name> placeholder expands to the four critics)."""
        import re

        from hyperresearch.core.contracts import _skills_root

        roles = set(list_roles())
        for path in sorted(_skills_root().glob("hyperresearch-*.md")):
            for name in re.findall(r"--role (\S+)`", path.read_text(encoding="utf-8")):
                if name == "<critic-name>-critic":
                    continue
                assert name in roles, (path.name, name)
