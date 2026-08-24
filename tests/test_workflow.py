"""Static contract tests for the reusable GitHub Actions workflow."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "governance-check.yml"


def _workflow() -> str:
    return WORKFLOW.read_text()


def test_target_branch_defaults_to_dev():
    workflow = _workflow()

    assert "target-branch:" in workflow
    assert 'default: "dev"' in workflow
    assert "CONFIGURED_TARGET_BRANCH: ${{ inputs.target-branch }}" in workflow
    assert "PULL_REQUEST_BASE_BRANCH: ${{ github.base_ref }}" in workflow
    assert 'target_branch="${CONFIGURED_TARGET_BRANCH:-${PULL_REQUEST_BASE_BRANCH}}"' in workflow


def test_target_manifest_is_generated_and_verified_before_build():
    workflow = _workflow()
    generate = workflow.index("- name: Generate target manifest")
    build = workflow.index("- name: Build changed models")

    assert generate < build
    assert 'git worktree add --detach "${TARGET_WORKTREE}" "origin/${TARGET_BRANCH}"' in workflow
    assert '--target "${TARGET_MANIFEST_DBT_TARGET}"' in workflow
    assert '--target-path "${TARGET_MANIFEST_DIR}"' in workflow
    assert 'if [ ! -f "${TARGET_MANIFEST_DIR}/manifest.json" ]; then' in workflow


def test_target_worktree_uses_project_local_profile_by_default():
    workflow = _workflow()

    assert 'elif [ -f "${target_project_dir}/profiles.yml" ]; then' in workflow
    assert 'export DBT_PROFILES_DIR="${target_project_dir}"' in workflow


def test_build_and_governance_use_the_resolved_target_branch():
    workflow = _workflow()

    assert '--state "${{ runner.temp }}/target-manifest"' in workflow
    assert workflow.count("TARGET_BRANCH: ${{ steps.target-branch.outputs.branch }}") == 3
    assert workflow.count('"origin/${TARGET_BRANCH}"') >= 3
    assert "prod-manifest" not in workflow


def test_target_manifest_generation_is_skipped_without_catalog_build():
    workflow = _workflow()
    start = workflow.index("- name: Generate target manifest")
    end = workflow.index("- name: Build changed models")
    generate_block = workflow[start:end]

    assert "if: ${{ !inputs.skip-catalog }}" in generate_block


def test_missing_target_branch_and_manifest_fail_explicitly():
    workflow = _workflow()

    assert "No target branch is available" in workflow
    assert "Target branch 'origin/${target_branch}' is not available" in workflow
    assert "dbt parse did not produce ${TARGET_MANIFEST_DIR}/manifest.json" in workflow
