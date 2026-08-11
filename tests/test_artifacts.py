"""Artifact parsing, including cross-version normalization."""

from __future__ import annotations

import json

import pytest
from conftest import FIXTURES

from dbt_governance.artifacts import (
    ArtifactError,
    _build_test,
    _strip_package_prefix,
    load_catalog,
    load_manifest,
)


def test_strips_package_prefix_from_patch_path():
    """Older dbt emits package://path; newer emits a bare path. Both must
    compare equal to a git diff path."""
    assert _strip_package_prefix("my_project://models/marts/_models.yml") == "models/marts/_models.yml"
    assert _strip_package_prefix("models/marts/_models.yml") == "models/marts/_models.yml"
    assert _strip_package_prefix(None) is None


def test_test_column_falls_back_to_kwargs():
    """column_name is null on some logically column-scoped tests, which carry
    the column through test kwargs instead."""
    node = {
        "unique_id": "test.p.accepted_range_x",
        "name": "accepted_range_x",
        "column_name": None,
        "attached_node": "model.p.dim_example",
        "test_metadata": {"name": "accepted_range", "kwargs": {"column_name": "order_total"}},
    }
    test = _build_test(node)
    assert test.column_name == "order_total"
    assert test.test_name == "accepted_range"


def test_test_namespace_is_prefixed():
    node = {
        "unique_id": "test.p.pk",
        "name": "pk",
        "column_name": "id",
        "attached_node": "model.p.dim_example",
        "test_metadata": {"name": "primary_key", "namespace": "dbt_constraints", "kwargs": {}},
    }
    assert _build_test(node).test_name == "dbt_constraints.primary_key"


def test_test_falls_back_to_single_model_dependency():
    """Older manifests have no attached_node."""
    node = {
        "unique_id": "test.p.unique_x",
        "name": "unique_x",
        "column_name": "id",
        "depends_on": {"nodes": ["model.p.dim_example", "macro.x"]},
        "test_metadata": {"name": "unique", "kwargs": {}},
    }
    assert _build_test(node).model_unique_id == "model.p.dim_example"


def test_ambiguous_test_dependency_is_skipped():
    node = {
        "unique_id": "test.p.relationships_x",
        "name": "relationships_x",
        "depends_on": {"nodes": ["model.p.a", "model.p.b"]},
        "test_metadata": {"name": "relationships", "kwargs": {}},
    }
    assert _build_test(node) is None


def test_unsupported_schema_version_fails_loudly(tmp_path):
    """A misread field looks like a passing check, which is worse than an error."""
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v99.json",
                    "project_name": "p",
                },
                "nodes": {},
            }
        )
    )
    with pytest.raises(ArtifactError, match="v99"):
        load_manifest(path)


def test_missing_manifest_gives_actionable_error(tmp_path):
    with pytest.raises(ArtifactError, match="dbt parse"):
        load_manifest(tmp_path / "absent.json")


def test_fixture_manifest_excludes_package_models():
    manifest = load_manifest(FIXTURES / "manifest.json")
    assert manifest.project_name == "governance_fixture"
    assert all(model.package_name == "governance_fixture" for model in manifest.models)


def test_fixture_manifest_resolves_inherited_tags():
    manifest = load_manifest(FIXTURES / "manifest.json")
    by_name = {model.name: model for model in manifest.models}

    # Declares no tags of its own; both come from dbt_project.yml.
    assert sorted(by_name["stg_project_tagged_only"].tags) == ["customer", "internal"]

    # dbt appends tags across nested folder levels.
    assert sorted(by_name["fct_nested_tags"].tags) == ["confidential", "finance"]


def test_fixture_manifest_normalizes_patch_paths():
    manifest = load_manifest(FIXTURES / "manifest.json")
    by_name = {model.name: model for model in manifest.models}
    assert by_name["dim_fully_documented"].patch_path == "models/marts/_models.yml"
    assert by_name["dim_no_yaml_entry"].patch_path is None


def test_layer_is_derived_from_file_path():
    manifest = load_manifest(FIXTURES / "manifest.json")
    by_name = {model.name: model for model in manifest.models}
    assert by_name["stg_project_tagged_only"].layer == "staging"
    assert by_name["dim_fully_documented"].layer == "marts"


def test_catalog_column_names_are_upper_cased():
    catalog = load_catalog(FIXTURES / "catalog.json")
    columns = catalog.columns("model.governance_fixture.dim_zero_documented_columns")
    assert columns == {"ORDER_KEY", "ORDER_TOTAL", "ORDER_STATUS"}


def test_catalog_omits_ephemeral_and_unbuilt_models():
    catalog = load_catalog(FIXTURES / "catalog.json")
    assert not catalog.has("model.governance_fixture.int_ephemeral_documented")
    assert not catalog.has("model.governance_fixture.dim_not_built")


def test_catalog_seed_entries_do_not_affect_model_checks():
    """`dbt docs generate` catalogs seeds too. Their unique_ids are namespaced
    under seed.*, so they can never collide with a model lookup."""
    catalog = load_catalog(FIXTURES / "catalog.json")
    seeds = [uid for uid in catalog.columns_by_node if uid.startswith("seed.")]
    assert seeds, "fixture catalog should contain seeds, proving they are harmless"

    manifest = load_manifest(FIXTURES / "manifest.json")
    assert all(not model.unique_id.startswith("seed.") for model in manifest.models)
