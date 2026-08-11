"""Golden test: the exact violation set produced by the fixture project.

The manifest is real dbt parse output, not a hand-written stub, so this test
also guards against dbt changing where fields live.
"""

from __future__ import annotations

import datetime as _dt

from conftest import FIXTURES

from dbt_governance.artifacts import load_catalog, load_manifest
from dbt_governance.cli import evaluate
from dbt_governance.config import load_config

# (model, rule_id, severity, column)
EXPECTED = {
    ("dim_bad_tag", "TAG001", "error", None),
    ("dim_bad_tag", "TAG002", "error", None),
    ("dim_missing_data_type", "DOC007", "error", "region_key"),
    ("dim_no_yaml_entry", "DOC001", "error", None),
    ("dim_not_built", "DOC009", "error", None),
    ("dim_placeholder_description", "DOC006", "error", "product_key"),
    ("dim_untested_key", "DOC008", "error", "invoice_id"),
    ("dim_zero_documented_columns", "DOC004", "error", None),
    ("legacy_expired", "EXEMPT001", "error", None),
    ("stg_partial_columns", "DOC004", "warning", None),
}

CLEAN_MODELS = {
    "dim_fully_documented",
    "stg_project_tagged_only",
    "fct_nested_tags",
    "int_ephemeral_documented",
}


def _evaluate():
    manifest = load_manifest(FIXTURES / "manifest.json")
    catalog = load_catalog(FIXTURES / "catalog.json")
    config = load_config(FIXTURES / "dbt_project" / "governance_rules.yml")
    # Pinned so the expired-exemption case does not depend on the run date.
    return evaluate(manifest.models, manifest, catalog, config, today=_dt.date(2026, 8, 11))


def test_violation_set_matches_exactly():
    violations, _ = _evaluate()
    actual = {(v.model, v.rule_id, v.severity, v.column) for v in violations}

    assert actual == EXPECTED, f"unexpected: {sorted(actual - EXPECTED)}\nmissing: {sorted(EXPECTED - actual)}"


def test_compliant_models_produce_no_violations():
    violations, _ = _evaluate()
    offenders = {v.model for v in violations} & CLEAN_MODELS
    assert offenders == set()


def test_project_level_tag_inheritance_passes():
    """A YAML-file-parsing implementation would wrongly fail this model."""
    violations, _ = _evaluate()
    assert not [v for v in violations if v.model == "stg_project_tagged_only"]


def test_ephemeral_model_is_not_penalised_for_absent_catalog_entry():
    violations, _ = _evaluate()
    assert not [v for v in violations if v.model == "int_ephemeral_documented"]


def test_zero_documented_columns_reports_all_three():
    violations, _ = _evaluate()
    violation = next(v for v in violations if v.model == "dim_zero_documented_columns")
    assert "3 of 3" in violation.message
    assert {"ORDER_KEY", "ORDER_TOTAL", "ORDER_STATUS"} <= set(violation.message.replace(",", " ").split())


def test_active_exemption_is_skipped_not_failed():
    violations, skipped = _evaluate()
    assert [name for name, _ in skipped] == ["legacy_active"]
    assert not [v for v in violations if v.model == "legacy_active"]


def test_run_fails_overall():
    violations, _ = _evaluate()
    assert any(v.is_error for v in violations)
