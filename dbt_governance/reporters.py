"""Output formats: console, GitHub Actions annotations, markdown summary."""

from __future__ import annotations

from collections import defaultdict

from .violation import Violation


def console(violations: list[Violation], checked: int, skipped: list[tuple[str, str]]) -> str:
    lines: list[str] = []

    if skipped:
        lines.append(f"Exempt models skipped ({len(skipped)}):")
        for name, reason in skipped:
            lines.append(f"  - {name}: {reason}")
        lines.append("")

    if not violations:
        lines.append(f"All governance checks passed across {checked} model(s).")
        return "\n".join(lines)

    by_model: dict[str, list[Violation]] = defaultdict(list)
    for violation in violations:
        by_model[violation.model].append(violation)

    for model in sorted(by_model):
        lines.append(model)
        for violation in sorted(by_model[model], key=lambda v: (v.rule_id, v.column or "")):
            marker = "ERROR  " if violation.is_error else "warning"
            target = f"{violation.column}: " if violation.column else ""
            lines.append(f"  {marker} {violation.rule_id}  {target}{violation.message}")
        lines.append("")

    errors = sum(1 for v in violations if v.is_error)
    warnings = sum(1 for v in violations if v.is_warning)
    lines.append(f"{checked} model(s) checked: {errors} error(s), {warnings} warning(s).")
    return "\n".join(lines)


def annotations(violations: list[Violation]) -> str:
    """GitHub Actions workflow commands, rendering violations inline on the diff."""
    lines = []
    for violation in violations:
        level = "error" if violation.is_error else "warning"
        title = f"{violation.rule_id}{f' ({violation.column})' if violation.column else ''}"
        message = _escape(f"{violation.model}: {violation.message}")
        lines.append(f"::{level} file={violation.file_path},title={_escape(title)}::{message}")
    return "\n".join(lines)


def _escape(text: str) -> str:
    """Escape per GitHub's workflow command rules."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")


def markdown(violations: list[Violation], checked: int, skipped: list[tuple[str, str]]) -> str:
    errors = [v for v in violations if v.is_error]
    warnings = [v for v in violations if v.is_warning]

    if not violations:
        header = f"### dbt governance checks passed\n\n{checked} model(s) checked, no violations."
        return header + _skipped_section(skipped)

    status = "failed" if errors else "passed with warnings"
    lines = [
        f"### dbt governance checks {status}",
        "",
        f"{checked} model(s) checked: **{len(errors)} error(s)**, {len(warnings)} warning(s).",
        "",
        "| Severity | Rule | Model | Column | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]

    for violation in sorted(violations, key=lambda v: (not v.is_error, v.model, v.rule_id, v.column or "")):
        severity = "error" if violation.is_error else "warning"
        column = f"`{violation.column}`" if violation.column else ""
        detail = violation.message.replace("|", "\\|")
        lines.append(f"| {severity} | {violation.rule_id} | `{violation.model}` | {column} | {detail} |")

    return "\n".join(lines) + _skipped_section(skipped)


def _skipped_section(skipped: list[tuple[str, str]]) -> str:
    if not skipped:
        return "\n"
    lines = ["", "", "<details><summary>Exempt models skipped</summary>", ""]
    for name, reason in skipped:
        lines.append(f"- `{name}`: {reason}")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)
