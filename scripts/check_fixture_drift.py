#!/usr/bin/env python3
"""Detect drift between the committed fixture manifest and fresh dbt output.

The committed manifest lets the test suite run without dbt installed, but a
stale fixture would let the golden test pass against a reality it no longer
reflects. This compares only the fields the checker actually reads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED = REPO_ROOT / "fixtures" / "manifest.json"
FRESH = REPO_ROOT / "fixtures" / "dbt_project" / "target" / "manifest.json"

# Everything the rule engines depend on. Drift outside these fields is
# irrelevant noise (timestamps, invocation ids, compiled SQL).
MODEL_FIELDS = ("original_file_path", "patch_path", "description", "tags")


def _load(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"error: {path} not found; run `dbt parse` in fixtures/dbt_project first")
    return json.loads(path.read_text())


def _models(manifest: dict) -> dict[str, dict]:
    return {
        unique_id: node
        for unique_id, node in (manifest.get("nodes") or {}).items()
        if node.get("resource_type") == "model"
    }


def _column_docs(node: dict) -> dict[str, tuple[str, str | None]]:
    return {
        name.lower(): (column.get("description") or "", column.get("data_type"))
        for name, column in (node.get("columns") or {}).items()
    }


def main() -> int:
    committed = _models(_load(COMMITTED))
    fresh = _models(_load(FRESH))
    problems: list[str] = []

    for unique_id in sorted(set(committed) | set(fresh)):
        if unique_id not in committed:
            problems.append(f"{unique_id}: present in fresh parse, absent from committed fixture")
            continue
        if unique_id not in fresh:
            problems.append(f"{unique_id}: present in committed fixture, absent from fresh parse")
            continue

        for field in MODEL_FIELDS:
            old, new = committed[unique_id].get(field), fresh[unique_id].get(field)
            if isinstance(old, list) and isinstance(new, list):
                old, new = sorted(old), sorted(new)
            if old != new:
                problems.append(f"{unique_id}.{field}: committed={old!r} fresh={new!r}")

        old_config = (committed[unique_id].get("config") or {}).get("materialized")
        new_config = (fresh[unique_id].get("config") or {}).get("materialized")
        if old_config != new_config:
            problems.append(f"{unique_id}.materialized: committed={old_config!r} fresh={new_config!r}")

        if _column_docs(committed[unique_id]) != _column_docs(fresh[unique_id]):
            problems.append(f"{unique_id}.columns: documented columns differ")

    if problems:
        print("Fixture manifest has drifted from fresh dbt output:\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nRefresh it with:\n"
            "  cd fixtures/dbt_project && DBT_PROFILES_DIR=. dbt parse\n"
            "  cp fixtures/dbt_project/target/manifest.json fixtures/manifest.json\n"
            "and re-check the expectations in tests/test_golden.py."
        )
        return 1

    print(f"Fixture manifest matches fresh dbt output across {len(fresh)} model(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
