"""Rule configuration loading, layer resolution, and exemptions."""

from __future__ import annotations

import datetime as _dt
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ERROR = "error"
WARNING = "warning"
IGNORE = "ignore"
_SEVERITIES = (ERROR, WARNING, IGNORE)

SUPPORTED_CONFIG_VERSION = 1


class ConfigError(Exception):
    """Raised when governance_rules.yml is malformed."""


@dataclass(frozen=True)
class Setting:
    """A single rule setting: its value plus the severity when violated."""

    value: Any
    severity: str = ERROR

    @property
    def enabled(self) -> bool:
        return self.severity != IGNORE and bool(self.value)


@dataclass(frozen=True)
class Exemption:
    path: str
    reason: str
    expires: _dt.date

    def matches(self, file_path: str) -> bool:
        return fnmatch.fnmatch(file_path, self.path)

    def is_expired(self, today: _dt.date) -> bool:
        return today > self.expires


@dataclass
class GovernanceConfig:
    defaults: dict[str, dict[str, Any]] = field(default_factory=dict)
    layers: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    exemptions: list[Exemption] = field(default_factory=list)

    def section(self, name: str, layer: str | None = None) -> dict[str, Setting]:
        """Return a rule section with layer overrides applied."""
        base = self.defaults.get(name, {})
        override = self.layers.get(layer or "", {}).get(name, {})
        merged = {key: _merge_raw(base.get(key), override.get(key)) for key in set(base) | set(override)}
        return {key: _normalize(raw) for key, raw in merged.items()}

    def exemption_for(self, file_path: str) -> Exemption | None:
        for exemption in self.exemptions:
            if exemption.matches(file_path):
                return exemption
        return None


def _merge_raw(base: Any, override: Any) -> Any:
    """Merge an override onto a base setting, preserving inherited values.

    A layer override of ``{severity: warning}`` keeps the default's value; only
    an explicit ``value`` key (or a bare scalar) replaces it.
    """
    if override is None:
        return base
    if isinstance(override, dict):
        base_dict = base if isinstance(base, dict) else {"value": base}
        return {**base_dict, **override}
    return {"value": override, "severity": base.get("severity", ERROR) if isinstance(base, dict) else ERROR}


def _normalize(raw: Any) -> Setting:
    if isinstance(raw, dict) and ("value" in raw or "severity" in raw):
        severity = raw.get("severity", ERROR)
        if severity not in _SEVERITIES:
            raise ConfigError(f"invalid severity {severity!r}, expected one of {_SEVERITIES}")
        return Setting(value=raw.get("value", True), severity=severity)
    return Setting(value=raw, severity=ERROR)


def load_config(path: str | Path) -> GovernanceConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"rules file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")

    version = raw.get("version", SUPPORTED_CONFIG_VERSION)
    if version != SUPPORTED_CONFIG_VERSION:
        raise ConfigError(
            f"unsupported config version {version!r}; this build understands version {SUPPORTED_CONFIG_VERSION}"
        )

    return GovernanceConfig(
        defaults=raw.get("defaults") or {},
        layers=raw.get("layers") or {},
        exemptions=[_parse_exemption(item, path) for item in raw.get("exemptions") or []],
    )


def _parse_exemption(item: Any, source: Path) -> Exemption:
    if not isinstance(item, dict):
        raise ConfigError(f"{source}: each exemption must be a mapping, got {type(item).__name__}")

    missing = [key for key in ("path", "reason", "expires") if not item.get(key)]
    if missing:
        raise ConfigError(
            f"{source}: exemption {item.get('path', '<unnamed>')!r} is missing required field(s): "
            f"{', '.join(missing)}. An exemption without an expiry never gets revisited."
        )

    expires = item["expires"]
    if isinstance(expires, _dt.datetime):
        expires = expires.date()
    elif isinstance(expires, str):
        try:
            expires = _dt.date.fromisoformat(expires)
        except ValueError as exc:
            raise ConfigError(f"{source}: exemption {item['path']!r} has invalid expires date {expires!r}") from exc
    elif not isinstance(expires, _dt.date):
        raise ConfigError(f"{source}: exemption {item['path']!r} has invalid expires date {expires!r}")

    return Exemption(path=str(item["path"]), reason=str(item["reason"]), expires=expires)
