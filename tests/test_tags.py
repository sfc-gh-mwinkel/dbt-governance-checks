"""Tag coverage rules."""

from __future__ import annotations

from conftest import make_config, make_model, rule_ids

from dbt_governance.rules import tags
from dbt_governance.rules.tags import MISSING_REQUIRED_TAG, TAG_OUTSIDE_VOCABULARY


def test_model_with_both_required_groups_passes():
    model = make_model(tags=["finance", "internal"])
    assert tags.check(model, make_config()) == []


def test_tags_inherited_from_project_yml_are_honoured():
    """The manifest resolves inheritance, so a model declaring no tags of its
    own still passes when dbt_project.yml supplies them."""
    model = make_model(tags=["customer", "confidential"])
    assert tags.check(model, make_config()) == []


def test_missing_domain_tag_is_reported():
    model = make_model(tags=["internal"])
    violations = tags.check(model, make_config())
    assert rule_ids(violations) == [MISSING_REQUIRED_TAG]
    assert "domain" in violations[0].message


def test_missing_both_groups_reports_both():
    model = make_model(tags=[])
    assert rule_ids(tags.check(model, make_config())) == [MISSING_REQUIRED_TAG] * 2


def test_misspelled_tag_is_rejected_by_vocabulary():
    """A typo satisfies a presence check while leaving the model ungoverned."""
    model = make_model(tags=["finance", "confidental"])
    violations = tags.check(model, make_config())
    assert rule_ids(violations) == [MISSING_REQUIRED_TAG, TAG_OUTSIDE_VOCABULARY]


def test_additional_allowed_tags_do_not_trip_vocabulary():
    model = make_model(tags=["finance", "internal", "nightly", "pii"])
    assert tags.check(model, make_config()) == []


def test_vocabulary_check_can_be_disabled():
    config = make_config({"defaults": {"tags": {"allowed_only": False}}})
    model = make_model(tags=["finance", "internal", "anything_goes"])
    assert tags.check(model, config) == []


def test_tag_comparison_is_case_insensitive():
    model = make_model(tags=["Finance", "INTERNAL"])
    assert tags.check(model, make_config()) == []


def test_severity_can_be_downgraded_to_warning():
    config = make_config(
        {"defaults": {"tags": {"require_any_of_group": {"value": {"domain": ["finance"]}, "severity": "warning"}}}}
    )
    violations = tags.check(make_model(tags=[]), config)
    assert [v.severity for v in violations] == ["warning"]


def test_ignore_severity_disables_the_rule():
    config = make_config({"defaults": {"tags": {"require_any_of_group": {"severity": "ignore"}}}})
    assert tags.check(make_model(tags=[]), config) == []
