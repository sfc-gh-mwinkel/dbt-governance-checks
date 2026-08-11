"""Documentation completeness rules.

The manifest only knows the columns that were *declared* in YAML, so it cannot
prove documentation is complete: a model documenting zero columns satisfies
every column-level rule vacuously. catalog.json supplies the columns the model
actually returns, which is what closes that loophole.
"""

from __future__ import annotations

import fnmatch

from ..artifacts import Catalog, Manifest, ModelNode
from ..config import IGNORE, GovernanceConfig, Setting
from ..violation import Violation

NO_YAML_ENTRY = "DOC001"
MODEL_DESCRIPTION_MISSING = "DOC002"
MODEL_DESCRIPTION_PLACEHOLDER = "DOC003"
UNDOCUMENTED_COLUMNS = "DOC004"
COLUMN_DESCRIPTION_MISSING = "DOC005"
COLUMN_DESCRIPTION_PLACEHOLDER = "DOC006"
COLUMN_DATA_TYPE_MISSING = "DOC007"
KEY_COLUMN_UNTESTED = "DOC008"
MODEL_MISSING_FROM_CATALOG = "DOC009"
DESCRIPTION_TOO_SHORT = "DOC010"


def check(
    model: ModelNode,
    manifest: Manifest,
    catalog: Catalog | None,
    config: GovernanceConfig,
) -> list[Violation]:
    settings = config.section("documentation", model.layer)
    violations: list[Violation] = []

    placeholders = _placeholders(settings)
    min_length = _min_length(settings)

    yaml_entry = settings.get("require_yaml_entry")
    if yaml_entry and yaml_entry.enabled and model.patch_path is None:
        # Every remaining documentation rule would restate this one finding.
        return [
            _violation(
                NO_YAML_ENTRY,
                yaml_entry,
                "model has no YAML entry, so nothing about it is documented",
                model,
            )
        ]

    violations.extend(_check_model_description(model, settings, placeholders, min_length))
    violations.extend(_check_columns(model, settings, placeholders, min_length))
    violations.extend(_check_completeness(model, catalog, settings))
    violations.extend(_check_key_column_tests(model, manifest, settings))

    return violations


def _placeholders(settings: dict[str, Setting]) -> set[str]:
    setting = settings.get("placeholder_denylist")
    if not setting or setting.severity == IGNORE:
        return set()
    return {str(value).strip().lower() for value in setting.value or []}


def _min_length(settings: dict[str, Setting]) -> int:
    setting = settings.get("min_description_length")
    if not setting or setting.severity == IGNORE:
        return 0
    try:
        return int(setting.value or 0)
    except (TypeError, ValueError):
        return 0


def _is_placeholder(text: str, placeholders: set[str]) -> bool:
    return text.strip().lower() in placeholders


def _violation(rule_id: str, setting: Setting, message: str, model: ModelNode, column: str | None = None) -> Violation:
    return Violation(
        rule_id=rule_id,
        severity=setting.severity,
        message=message,
        model=model.name,
        file_path=model.yaml_or_sql_path,
        column=column,
    )


def _check_model_description(
    model: ModelNode, settings: dict[str, Setting], placeholders: set[str], min_length: int
) -> list[Violation]:
    setting = settings.get("require_model_description")
    if not setting or not setting.enabled:
        return []

    description = model.description.strip()
    if not description:
        return [_violation(MODEL_DESCRIPTION_MISSING, setting, "model has no description", model)]
    if _is_placeholder(description, placeholders):
        return [
            _violation(
                MODEL_DESCRIPTION_PLACEHOLDER,
                setting,
                f"model description is placeholder text ({description!r})",
                model,
            )
        ]
    if min_length and len(description) < min_length:
        return [
            _violation(
                DESCRIPTION_TOO_SHORT,
                setting,
                f"model description is {len(description)} characters, minimum is {min_length}",
                model,
            )
        ]
    return []


def _check_columns(
    model: ModelNode, settings: dict[str, Setting], placeholders: set[str], min_length: int
) -> list[Violation]:
    violations: list[Violation] = []
    descriptions = settings.get("require_column_descriptions")
    data_types = settings.get("require_column_data_types")

    for column in model.columns.values():
        if descriptions and descriptions.enabled:
            description = column.description.strip()
            if not description:
                violations.append(
                    _violation(
                        COLUMN_DESCRIPTION_MISSING, descriptions, "column has no description", model, column.name
                    )
                )
            elif _is_placeholder(description, placeholders):
                violations.append(
                    _violation(
                        COLUMN_DESCRIPTION_PLACEHOLDER,
                        descriptions,
                        f"column description is placeholder text ({description!r})",
                        model,
                        column.name,
                    )
                )
            elif min_length and len(description) < min_length:
                violations.append(
                    _violation(
                        DESCRIPTION_TOO_SHORT,
                        descriptions,
                        f"column description is {len(description)} characters, minimum is {min_length}",
                        model,
                        column.name,
                    )
                )

        if data_types and data_types.enabled and not (column.data_type or "").strip():
            violations.append(
                _violation(COLUMN_DATA_TYPE_MISSING, data_types, "column has no data_type", model, column.name)
            )

    return violations


def _check_completeness(model: ModelNode, catalog: Catalog | None, settings: dict[str, Setting]) -> list[Violation]:
    setting = settings.get("require_all_columns_documented")
    if not setting or not setting.enabled:
        return []

    # Ephemeral models are never materialized, so they have no catalog entry.
    # Their declared columns are still checked by the rules above.
    if model.is_ephemeral:
        return []

    if catalog is None:
        return [
            _violation(
                MODEL_MISSING_FROM_CATALOG,
                setting,
                "cannot verify column completeness without catalog.json; run `dbt docs generate` "
                "or set require_all_columns_documented severity to ignore",
                model,
            )
        ]

    if not catalog.has(model.unique_id):
        # Silently skipping here would let the strongest rule stop running the
        # moment a build failed, which is precisely when it matters most.
        return [
            _violation(
                MODEL_MISSING_FROM_CATALOG,
                setting,
                "model is absent from catalog.json, so completeness could not be verified; "
                "it was probably not built before `dbt docs generate` ran",
                model,
            )
        ]

    actual = catalog.columns(model.unique_id)
    documented = {name.upper() for name in model.columns}
    undocumented = sorted(actual - documented)
    if not undocumented:
        return []

    return [
        _violation(
            UNDOCUMENTED_COLUMNS,
            setting,
            f"{len(undocumented)} of {len(actual)} columns are undocumented: {', '.join(undocumented)}",
            model,
        )
    ]


def _check_key_column_tests(model: ModelNode, manifest: Manifest, settings: dict[str, Setting]) -> list[Violation]:
    patterns_setting = settings.get("key_column_patterns")
    tests_setting = settings.get("key_column_required_tests")
    if not patterns_setting or not patterns_setting.enabled or not tests_setting or not tests_setting.enabled:
        return []

    patterns = [str(pattern).lower() for pattern in patterns_setting.value or []]
    required = {str(name).lower() for name in tests_setting.value or []}
    if not patterns or not required:
        return []

    tested_columns = {
        test.column_name.lower()
        for test in manifest.tests_for(model.unique_id)
        if test.column_name and test.test_name.lower() in required
    }

    violations: list[Violation] = []
    for column in model.columns:
        lowered = column.lower()
        if not any(fnmatch.fnmatch(lowered, pattern) for pattern in patterns):
            continue
        if lowered in tested_columns:
            continue
        violations.append(
            _violation(
                KEY_COLUMN_UNTESTED,
                tests_setting,
                f"looks like a key column but has none of the required tests ({', '.join(sorted(required))})",
                model,
                column,
            )
        )

    return violations
