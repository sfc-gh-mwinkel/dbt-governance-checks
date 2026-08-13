"""Command line entry point."""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

from . import reporters
from .artifacts import ArtifactError, Catalog, Manifest, load_catalog, load_manifest
from .changed import GitError, changed_files, select_changed_models
from .config import ConfigError, GovernanceConfig, load_config
from .rules import documentation, tags
from .violation import Violation

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_USAGE = 2

EXPIRED_EXEMPTION = "EXEMPT001"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dbt-governance",
        description="Enforce dbt tag coverage and documentation completeness.",
    )
    parser.add_argument("--project-dir", default=".", help="dbt project root (default: current directory)")
    parser.add_argument("--manifest", help="path to manifest.json (default: <project-dir>/target/manifest.json)")
    parser.add_argument(
        "--catalog",
        help="path to catalog.json (default: <project-dir>/target/catalog.json). "
        "Required for column completeness checks.",
    )
    parser.add_argument("--rules", help="path to governance_rules.yml (default: <project-dir>/governance_rules.yml)")
    parser.add_argument("--changed-only", action="store_true", help="only check models changed relative to --base-ref")
    parser.add_argument("--base-ref", default="origin/main", help="base ref for --changed-only (default: origin/main)")
    parser.add_argument(
        "--format",
        default="console",
        choices=["console", "annotations", "markdown"],
        help="output format (default: console)",
    )
    parser.add_argument("--output", help="also write the report to this file")
    parser.add_argument("--warnings-as-errors", action="store_true", help="fail the run on warnings as well as errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_dir = Path(args.project_dir).resolve()

    manifest_path = Path(args.manifest) if args.manifest else project_dir / "target" / "manifest.json"
    catalog_path = Path(args.catalog) if args.catalog else project_dir / "target" / "catalog.json"
    rules_path = Path(args.rules) if args.rules else project_dir / "governance_rules.yml"

    try:
        config = load_config(rules_path, project_dir=project_dir)
        manifest = load_manifest(manifest_path)
    except (ConfigError, ArtifactError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    catalog: Catalog | None = None
    if catalog_path.is_file():
        try:
            catalog = load_catalog(catalog_path)
        except ArtifactError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    try:
        models = (
            select_changed_models(manifest, changed_files(args.base_ref, project_dir))
            if args.changed_only
            else manifest.models
        )
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    violations, skipped = evaluate(models, manifest, catalog, config)

    report = {
        "console": reporters.console,
        "markdown": reporters.markdown,
    }.get(args.format)
    text = reporters.annotations(violations) if report is None else report(violations, len(models), skipped)

    if text:
        print(text)
    if args.output:
        Path(args.output).write_text(text + "\n")

    failed = any(v.is_error for v in violations) or (args.warnings_as_errors and bool(violations))
    return EXIT_VIOLATIONS if failed else EXIT_OK


def evaluate(
    models: list,
    manifest: Manifest,
    catalog: Catalog | None,
    config: GovernanceConfig,
    today: _dt.date | None = None,
) -> tuple[list[Violation], list[tuple[str, str]]]:
    today = today or _dt.date.today()
    violations: list[Violation] = []
    skipped: list[tuple[str, str]] = []

    for model in models:
        exemption = config.exemption_for(model.original_file_path)
        if exemption is not None:
            if exemption.is_expired(today):
                violations.append(
                    Violation(
                        rule_id=EXPIRED_EXEMPTION,
                        severity="error",
                        message=(
                            f"exemption for '{exemption.path}' expired on {exemption.expires.isoformat()} "
                            f"({exemption.reason}); renew it deliberately or document the model"
                        ),
                        model=model.name,
                        file_path=model.original_file_path,
                    )
                )
            else:
                skipped.append((model.name, exemption.reason))
            continue

        violations.extend(tags.check(model, config))
        violations.extend(documentation.check(model, manifest, catalog, config))

    return violations, skipped


if __name__ == "__main__":
    sys.exit(main())
