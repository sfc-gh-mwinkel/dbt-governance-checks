"""Rule configuration: severity merging and exemption handling."""

from __future__ import annotations

import datetime as _dt

import pytest
import yaml
from conftest import make_config

from dbt_governance.config import ERROR, ConfigError, load_config


def _write(tmp_path, data):
    path = tmp_path / "governance_rules.yml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_layer_override_of_severity_preserves_inherited_value():
    """A layer override of {severity: warning} must not blank out the value."""
    config = make_config(
        {"layers": {"staging": {"documentation": {"require_column_descriptions": {"severity": "warning"}}}}}
    )
    setting = config.section("documentation", "staging")["require_column_descriptions"]
    assert setting.value is True
    assert setting.severity == "warning"
    assert setting.enabled


def test_defaults_apply_when_layer_has_no_override():
    config = make_config()
    assert config.section("documentation", "marts")["require_column_descriptions"].severity == ERROR


def test_unknown_layer_falls_back_to_defaults():
    config = make_config()
    assert config.section("documentation", "no_such_layer")["require_yaml_entry"].enabled


def test_ignore_severity_disables_a_rule():
    config = make_config({"defaults": {"documentation": {"require_yaml_entry": {"severity": "ignore"}}}})
    assert not config.section("documentation")["require_yaml_entry"].enabled


def test_invalid_severity_is_rejected(tmp_path):
    path = _write(tmp_path, {"version": 1, "defaults": {"tags": {"allowed_only": {"severity": "fatal"}}}})
    with pytest.raises(ConfigError, match="invalid severity"):
        load_config(path).section("tags")


def test_unsupported_config_version_is_rejected(tmp_path):
    path = _write(tmp_path, {"version": 99})
    with pytest.raises(ConfigError, match="unsupported config version"):
        load_config(path)


def test_missing_rules_file_is_reported(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.yml")


def test_exemption_without_expiry_is_rejected(tmp_path):
    """An exemption with no expiry never gets revisited."""
    path = _write(tmp_path, {"version": 1, "exemptions": [{"path": "models/legacy/**", "reason": "backlog"}]})
    with pytest.raises(ConfigError, match="expires"):
        load_config(path)


def test_exemption_without_reason_is_rejected(tmp_path):
    path = _write(tmp_path, {"version": 1, "exemptions": [{"path": "models/legacy/**", "expires": "2030-01-01"}]})
    with pytest.raises(ConfigError, match="reason"):
        load_config(path)


def test_exemption_matches_by_glob(tmp_path):
    path = _write(
        tmp_path,
        {
            "version": 1,
            "exemptions": [{"path": "models/legacy/**", "reason": "backlog", "expires": "2030-01-01"}],
        },
    )
    config = load_config(path)
    assert config.exemption_for("models/legacy/deep/old.sql") is not None
    assert config.exemption_for("models/marts/dim_a.sql") is None


def test_expiry_is_detected(tmp_path):
    path = _write(
        tmp_path,
        {
            "version": 1,
            "exemptions": [{"path": "models/legacy/**", "reason": "backlog", "expires": "2026-06-30"}],
        },
    )
    exemption = load_config(path).exemption_for("models/legacy/old.sql")
    assert exemption.is_expired(_dt.date(2026, 7, 1))
    assert not exemption.is_expired(_dt.date(2026, 6, 30))


def test_invalid_expiry_date_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        {"version": 1, "exemptions": [{"path": "m/**", "reason": "r", "expires": "not-a-date"}]},
    )
    with pytest.raises(ConfigError, match="invalid expires"):
        load_config(path)
