"""Tag coverage rules.

dbt merges tags from dbt_project.yml (including nested folder paths), in-file
config() blocks, and YAML entries into node.tags at parse time. Reading
node.tags therefore satisfies "tags applied at any layer" without
reimplementing dbt's precedence rules.
"""

from __future__ import annotations

from ..artifacts import ModelNode
from ..config import GovernanceConfig
from ..violation import Violation

MISSING_REQUIRED_TAG = "TAG001"
TAG_OUTSIDE_VOCABULARY = "TAG002"


def check(model: ModelNode, config: GovernanceConfig) -> list[Violation]:
    settings = config.section("tags", model.layer)
    violations: list[Violation] = []
    model_tags = {tag.lower() for tag in model.tags}

    groups_setting = settings.get("require_any_of_group")
    groups: dict[str, list[str]] = groups_setting.value if groups_setting and groups_setting.enabled else {}

    for group_name, allowed in groups.items():
        allowed_lower = {str(tag).lower() for tag in allowed or []}
        if not allowed_lower or model_tags & allowed_lower:
            continue
        violations.append(
            Violation(
                rule_id=MISSING_REQUIRED_TAG,
                severity=groups_setting.severity,
                message=(
                    f"missing a '{group_name}' tag; expected one of "
                    f"{sorted(allowed_lower)} (tags may be set on the model, in a "
                    f"folder config, or in dbt_project.yml)"
                ),
                model=model.name,
                file_path=model.yaml_or_sql_path,
            )
        )

    allowed_only = settings.get("allowed_only")
    if allowed_only and allowed_only.enabled:
        vocabulary = {str(tag).lower() for tags in groups.values() for tag in tags or []}

        additional = settings.get("additional_allowed_tags")
        if additional and additional.severity != "ignore":
            vocabulary |= {str(tag).lower() for tag in additional.value or []}

        for tag in sorted(model_tags - vocabulary):
            violations.append(
                Violation(
                    rule_id=TAG_OUTSIDE_VOCABULARY,
                    severity=allowed_only.severity,
                    message=(
                        f"tag '{tag}' is not in the approved vocabulary; a misspelled tag "
                        "satisfies a presence check while leaving the model ungoverned"
                    ),
                    model=model.name,
                    file_path=model.yaml_or_sql_path,
                )
            )

    return violations
