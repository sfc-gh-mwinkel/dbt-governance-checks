"""Documentation completeness rules."""

from __future__ import annotations

from conftest import make_catalog, make_config, make_manifest, make_model, rule_ids

from dbt_governance.artifacts import ColumnTest
from dbt_governance.rules import documentation
from dbt_governance.rules.documentation import (
    COLUMN_DATA_TYPE_MISSING,
    COLUMN_DESCRIPTION_MISSING,
    COLUMN_DESCRIPTION_PLACEHOLDER,
    DESCRIPTION_TOO_SHORT,
    KEY_COLUMN_UNTESTED,
    MODEL_DESCRIPTION_MISSING,
    MODEL_MISSING_FROM_CATALOG,
    NO_YAML_ENTRY,
    UNDOCUMENTED_COLUMNS,
)

DOCUMENTED = {
    "customer_key": ("Surrogate key uniquely identifying the customer.", "number"),
    "customer_name": ("Registered legal name of the customer.", "varchar"),
}


def _check(model, catalog=None, config=None, tests=None):
    manifest = make_manifest([model], tests)
    return documentation.check(model, manifest, catalog, config or make_config())


def _key_test(model, column):
    return ColumnTest(test_name="unique", model_unique_id=model.unique_id, column_name=column)


def test_fully_documented_model_passes():
    model = make_model(columns=DOCUMENTED)
    catalog = make_catalog(model, ["customer_key", "customer_name"])
    assert _check(model, catalog, tests=[_key_test(model, "customer_key")]) == []


def test_model_without_yaml_entry_reports_once_only():
    """Every other documentation rule would just restate this finding."""
    model = make_model(patch_path=None, description="", columns={})
    assert rule_ids(_check(model)) == [NO_YAML_ENTRY]


def test_missing_model_description_is_reported():
    model = make_model(description="", columns=DOCUMENTED)
    catalog = make_catalog(model, ["customer_key", "customer_name"])
    violations = _check(model, catalog, tests=[_key_test(model, "customer_key")])
    assert rule_ids(violations) == [MODEL_DESCRIPTION_MISSING]


def test_zero_documented_columns_is_caught_only_by_the_catalog():
    """The core loophole: with no declared columns, every column rule passes
    vacuously, so the catalog is the only thing that can catch it."""
    model = make_model(columns={})

    # Without a catalog the tool can only say it could not verify completeness.
    assert rule_ids(_check(model, catalog=None)) == [MODEL_MISSING_FROM_CATALOG]

    catalog = make_catalog(model, ["order_key", "order_total", "order_status"])
    violations = _check(model, catalog)
    assert rule_ids(violations) == [UNDOCUMENTED_COLUMNS]
    assert "3 of 3" in violations[0].message


def test_partially_documented_columns_are_reported():
    model = make_model(columns=DOCUMENTED)
    catalog = make_catalog(model, ["customer_key", "customer_name", "created_at"])
    violations = _check(model, catalog, tests=[_key_test(model, "customer_key")])
    assert rule_ids(violations) == [UNDOCUMENTED_COLUMNS]
    assert "CREATED_AT" in violations[0].message


def test_column_matching_is_case_insensitive():
    """Snowflake reports upper-case column names; YAML is conventionally lower."""
    model = make_model(columns={"CUSTOMER_KEY": ("Surrogate key.", "number")})
    catalog = make_catalog(model, ["customer_key"])
    assert _check(model, catalog, tests=[_key_test(model, "CUSTOMER_KEY")]) == []


def test_missing_column_description_is_reported():
    model = make_model(columns={"customer_name": ("", "varchar")})
    catalog = make_catalog(model, ["customer_name"])
    assert rule_ids(_check(model, catalog)) == [COLUMN_DESCRIPTION_MISSING]


def test_placeholder_column_description_is_rejected():
    model = make_model(columns={"customer_name": ("  TODO  ", "varchar")})
    catalog = make_catalog(model, ["customer_name"])
    assert rule_ids(_check(model, catalog)) == [COLUMN_DESCRIPTION_PLACEHOLDER]


def test_missing_data_type_is_reported():
    model = make_model(columns={"customer_name": ("Registered legal name.", None)})
    catalog = make_catalog(model, ["customer_name"])
    assert rule_ids(_check(model, catalog)) == [COLUMN_DATA_TYPE_MISSING]


def test_min_description_length_is_enforced():
    config = make_config({"defaults": {"documentation": {"min_description_length": 20}}})
    model = make_model(columns={"customer_name": ("Name", "varchar")})
    catalog = make_catalog(model, ["customer_name"])
    assert rule_ids(_check(model, catalog, config)) == [DESCRIPTION_TOO_SHORT]


def test_untested_key_column_is_reported():
    model = make_model(columns={"invoice_id": ("Surrogate key for the invoice.", "number")})
    catalog = make_catalog(model, ["invoice_id"])
    assert rule_ids(_check(model, catalog)) == [KEY_COLUMN_UNTESTED]


def test_key_column_with_required_test_passes():
    model = make_model(columns={"invoice_id": ("Surrogate key for the invoice.", "number")})
    catalog = make_catalog(model, ["invoice_id"])
    assert _check(model, catalog, tests=[_key_test(model, "invoice_id")]) == []


def test_non_key_columns_need_no_test():
    model = make_model(columns={"invoice_amount": ("Invoice gross amount in USD.", "number")})
    catalog = make_catalog(model, ["invoice_amount"])
    assert _check(model, catalog) == []


def test_ephemeral_model_is_exempt_from_completeness():
    """Ephemeral models are never materialized, so they have no catalog entry."""
    model = make_model(columns=DOCUMENTED, materialized="ephemeral")
    violations = _check(model, catalog=make_catalog(model, []), tests=[_key_test(model, "customer_key")])
    assert violations == []


def test_model_absent_from_catalog_errors_rather_than_skipping():
    """A silent skip would stop the strongest rule running exactly when a build
    fails, which is when it matters most."""
    model = make_model(columns=DOCUMENTED)
    other = make_model(name="dim_other")
    violations = _check(model, make_catalog(other, ["x"]), tests=[_key_test(model, "customer_key")])
    assert rule_ids(violations) == [MODEL_MISSING_FROM_CATALOG]


def test_missing_catalog_entirely_is_reported():
    model = make_model(columns=DOCUMENTED)
    violations = _check(model, catalog=None, tests=[_key_test(model, "customer_key")])
    assert rule_ids(violations) == [MODEL_MISSING_FROM_CATALOG]


def test_completeness_can_be_disabled_without_a_catalog():
    config = make_config({"defaults": {"documentation": {"require_all_columns_documented": {"severity": "ignore"}}}})
    model = make_model(columns=DOCUMENTED)
    assert _check(model, catalog=None, config=config, tests=[_key_test(model, "customer_key")]) == []


def test_layer_override_downgrades_severity():
    config = make_config(
        {"layers": {"staging": {"documentation": {"require_all_columns_documented": {"severity": "warning"}}}}}
    )
    model = make_model(path="models/staging/stg_example.sql", columns={})
    catalog = make_catalog(model, ["order_id", "order_total"])
    violations = _check(model, catalog, config)
    assert [(v.rule_id, v.severity) for v in violations] == [(UNDOCUMENTED_COLUMNS, "warning")]


def test_namespaced_test_satisfies_key_column_rule():
    model = make_model(columns={"invoice_id": ("Surrogate key for the invoice.", "number")})
    catalog = make_catalog(model, ["invoice_id"])
    test = ColumnTest(
        test_name="dbt_constraints.primary_key",
        model_unique_id=model.unique_id,
        column_name="invoice_id",
    )
    assert _check(model, catalog, tests=[test]) == []
