"""Loading and normalizing dbt artifacts (manifest.json, catalog.json)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Manifest schema versions this build has been reasoned about against.
# Reading an unknown version silently is worse than failing: field locations
# move between versions and a misread field looks like a passing check.
MIN_MANIFEST_SCHEMA = 7
MAX_MANIFEST_SCHEMA = 20

_SCHEMA_VERSION_RE = re.compile(r"/v(\d+)\.json$")


class ArtifactError(Exception):
    """Raised when an artifact is missing, malformed, or an untested version."""


@dataclass(frozen=True)
class ColumnDoc:
    """A column as documented in YAML (via the manifest)."""

    name: str
    description: str
    data_type: str | None


@dataclass(frozen=True)
class ModelNode:
    unique_id: str
    name: str
    package_name: str
    original_file_path: str
    patch_path: str | None
    fqn: list[str]
    tags: list[str]
    description: str
    columns: dict[str, ColumnDoc]
    materialized: str
    is_ephemeral: bool

    @property
    def layer(self) -> str | None:
        """First directory beneath the model root, used for layer overrides."""
        parts = Path(self.original_file_path).parts
        return parts[1] if len(parts) > 2 else None

    @property
    def yaml_or_sql_path(self) -> str:
        return self.patch_path or self.original_file_path


@dataclass(frozen=True)
class ColumnTest:
    test_name: str
    model_unique_id: str
    column_name: str | None


@dataclass
class Manifest:
    project_name: str
    dbt_version: str
    schema_version: int
    models: list[ModelNode] = field(default_factory=list)
    tests: list[ColumnTest] = field(default_factory=list)

    def tests_for(self, model_unique_id: str) -> Iterator[ColumnTest]:
        for test in self.tests:
            if test.model_unique_id == model_unique_id:
                yield test


@dataclass
class Catalog:
    """Actual materialized columns, keyed by model unique_id.

    Column names are stored upper-cased because Snowflake reports them that way
    while YAML is conventionally lower-case. All comparisons must case-fold.
    """

    columns_by_node: dict[str, set[str]] = field(default_factory=dict)

    def has(self, unique_id: str) -> bool:
        return unique_id in self.columns_by_node

    def columns(self, unique_id: str) -> set[str]:
        return self.columns_by_node.get(unique_id, set())


def _read_json(path: str | Path, label: str) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ArtifactError(
            f"{label} not found at {path}. Run `dbt parse` (manifest) or `dbt docs generate` (catalog) first."
        )
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"{label} at {path} is not valid JSON: {exc}") from exc


def _schema_version(metadata: dict[str, Any], label: str) -> int:
    raw = metadata.get("dbt_schema_version", "")
    match = _SCHEMA_VERSION_RE.search(raw)
    if not match:
        raise ArtifactError(f"could not determine {label} schema version from {raw!r}")
    return int(match.group(1))


def _strip_package_prefix(patch_path: str | None) -> str | None:
    """Normalize patch_path across dbt versions.

    Older dbt emits ``package_name://models/foo.yml``; newer emits a bare
    project-relative path. Both must compare equal to a git diff path.
    """
    if not patch_path:
        return None
    _, separator, remainder = patch_path.partition("://")
    return remainder if separator else patch_path


def load_manifest(path: str | Path) -> Manifest:
    raw = _read_json(path, "manifest.json")
    metadata = raw.get("metadata") or {}
    schema_version = _schema_version(metadata, "manifest")

    if not MIN_MANIFEST_SCHEMA <= schema_version <= MAX_MANIFEST_SCHEMA:
        raise ArtifactError(
            f"manifest schema v{schema_version} has not been validated against this tool "
            f"(supported: v{MIN_MANIFEST_SCHEMA}-v{MAX_MANIFEST_SCHEMA}). "
            "Field locations move between versions, so this fails rather than risk a false pass."
        )

    project_name = metadata.get("project_name")
    if not project_name:
        raise ArtifactError("manifest metadata is missing project_name; cannot identify first-party models")

    manifest = Manifest(
        project_name=project_name,
        dbt_version=metadata.get("dbt_version", "unknown"),
        schema_version=schema_version,
    )

    for node in (raw.get("nodes") or {}).values():
        resource_type = node.get("resource_type")
        if resource_type == "model":
            # Installed packages appear in the manifest; linting them would
            # drown real violations in vendored noise.
            if node.get("package_name") != project_name:
                continue
            manifest.models.append(_build_model(node))
        elif resource_type == "test":
            test = _build_test(node)
            if test is not None:
                manifest.tests.append(test)

    manifest.models.sort(key=lambda m: m.unique_id)
    return manifest


def _build_model(node: dict[str, Any]) -> ModelNode:
    config = node.get("config") or {}
    materialized = config.get("materialized", "view")

    columns = {}
    for name, column in (node.get("columns") or {}).items():
        columns[name] = ColumnDoc(
            name=column.get("name", name),
            description=column.get("description") or "",
            data_type=column.get("data_type"),
        )

    return ModelNode(
        unique_id=node["unique_id"],
        name=node.get("name", ""),
        package_name=node.get("package_name", ""),
        original_file_path=node.get("original_file_path", ""),
        patch_path=_strip_package_prefix(node.get("patch_path")),
        fqn=list(node.get("fqn") or []),
        # dbt merges dbt_project.yml, folder configs, config() blocks and YAML
        # into node.tags at parse time, so inherited tags are already resolved.
        tags=list(node.get("tags") or []),
        description=node.get("description") or "",
        columns=columns,
        materialized=materialized,
        is_ephemeral=materialized == "ephemeral",
    )


def _build_test(node: dict[str, Any]) -> ColumnTest | None:
    test_metadata = node.get("test_metadata") or {}
    test_name = test_metadata.get("name") or node.get("name", "")

    model_unique_id = node.get("attached_node")
    if not model_unique_id:
        # Older manifests have no attached_node; fall back to the single model
        # dependency, which is how column tests are wired.
        model_deps = [dep for dep in (node.get("depends_on") or {}).get("nodes", []) if dep.startswith("model.")]
        if len(model_deps) != 1:
            return None
        model_unique_id = model_deps[0]

    # column_name is None on some logically column-scoped tests (accepted_range,
    # for example), where the column arrives through test kwargs instead.
    column_name = node.get("column_name") or (test_metadata.get("kwargs") or {}).get("column_name")

    namespace = test_metadata.get("namespace")
    if namespace:
        test_name = f"{namespace}.{test_name}"

    return ColumnTest(
        test_name=test_name,
        model_unique_id=model_unique_id,
        column_name=column_name if isinstance(column_name, str) else None,
    )


def load_catalog(path: str | Path) -> Catalog:
    raw = _read_json(path, "catalog.json")
    _schema_version(raw.get("metadata") or {}, "catalog")

    catalog = Catalog()
    for unique_id, entry in (raw.get("nodes") or {}).items():
        catalog.columns_by_node[unique_id] = {str(name).upper() for name in (entry.get("columns") or {})}
    return catalog
