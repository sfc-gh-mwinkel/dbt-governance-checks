"""Shared test helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"

sys.path.insert(0, str(REPO_ROOT))

from dbt_governance.artifacts import (  # noqa: E402
    Catalog,
    ColumnDoc,
    ColumnTest,
    Manifest,
    ModelNode,
)
from dbt_governance.config import GovernanceConfig, load_config  # noqa: E402


def make_model(
    name: str = "dim_example",
    *,
    path: str = "models/marts/dim_example.sql",
    patch_path: str | None = "models/marts/_models.yml",
    tags: list[str] | None = None,
    description: str = "A well documented example model.",
    columns: dict[str, tuple[str, str | None]] | None = None,
    materialized: str = "view",
) -> ModelNode:
    """Build a ModelNode directly, so rule tests need no dbt invocation.

    ``columns`` maps column name to ``(description, data_type)``.
    """
    return ModelNode(
        unique_id=f"model.test_project.{name}",
        name=name,
        package_name="test_project",
        original_file_path=path,
        patch_path=patch_path,
        fqn=["test_project", "marts", name],
        tags=tags if tags is not None else ["finance", "internal"],
        description=description,
        columns={
            column: ColumnDoc(name=column, description=desc, data_type=data_type)
            for column, (desc, data_type) in (columns or {}).items()
        },
        materialized=materialized,
        is_ephemeral=materialized == "ephemeral",
    )


def make_manifest(models: list[ModelNode], tests: list[ColumnTest] | None = None) -> Manifest:
    return Manifest(
        project_name="test_project",
        dbt_version="1.9.0",
        schema_version=12,
        models=models,
        tests=tests or [],
    )


def make_catalog(model: ModelNode, columns: list[str]) -> Catalog:
    return Catalog(columns_by_node={model.unique_id: {c.upper() for c in columns}})


def make_config(overrides: dict | None = None) -> GovernanceConfig:
    """Baseline config with every rule on, optionally deep-merged with overrides."""
    base = {
        "version": 1,
        "defaults": {
            "tags": {
                "require_any_of_group": {
                    "domain": ["finance", "risk", "customer", "ops"],
                    "classification": ["public", "internal", "confidential", "restricted"],
                },
                "allowed_only": True,
                "additional_allowed_tags": ["nightly", "pii"],
            },
            "documentation": {
                "require_yaml_entry": True,
                "require_model_description": True,
                "require_all_columns_documented": True,
                "require_column_descriptions": True,
                "require_column_data_types": True,
                "min_description_length": 0,
                "placeholder_denylist": ["todo", "tbd", "n/a", "?"],
                "key_column_patterns": ["*_id", "*_key", "*_sk", "id"],
                "key_column_required_tests": ["unique", "dbt_constraints.primary_key"],
            },
        },
    }
    if overrides:
        base = _deep_merge(base, overrides)
    return _config_from_dict(base)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _config_from_dict(data: dict) -> GovernanceConfig:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as handle:
        yaml.safe_dump(data, handle)
        temp_path = handle.name
    return load_config(temp_path)


def rule_ids(violations) -> list[str]:
    return sorted(v.rule_id for v in violations)


@pytest.fixture
def fixture_manifest_path() -> Path:
    return FIXTURES / "manifest.json"


@pytest.fixture
def fixture_catalog_path() -> Path:
    return FIXTURES / "catalog.json"


@pytest.fixture
def fixture_rules_path() -> Path:
    return FIXTURES / "dbt_project" / "governance_rules.yml"
