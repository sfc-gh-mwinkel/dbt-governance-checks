#!/usr/bin/env python3
"""Compare the fixture manifest across dbt distributions, on the fields the
checker actually reads."""

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

fresh = json.loads((REPO / "fixtures/dbt_project/target/manifest.json").read_text())
committed = json.loads((REPO / "fixtures/manifest.json").read_text())


def models(manifest):
    return {n["name"]: n for n in manifest["nodes"].values() if n["resource_type"] == "model"}


def show(label, manifest):
    md = manifest["metadata"]
    print(f"{label:14} schema={md['dbt_schema_version'].split('/')[-1]:14} dbt={md['dbt_version']}")


show("fresh parse", fresh)
show("committed", committed)

fm, om = models(fresh), models(committed)
print(f"\nmodels: fresh={len(fm)} committed={len(om)}\n")

print(f"{'model':<30} {'patch_path (fresh)':<44} tags")
for name in sorted(fm):
    print(f"{name:<30} {str(fm[name].get('patch_path')):<44} {sorted(fm[name]['tags'])}")

print("\n=== diffs on fields the checker reads ===")
diffs = 0
for name in sorted(set(fm) | set(om)):
    if name not in fm or name not in om:
        print(f"  {name}: present in only one manifest")
        diffs += 1
        continue
    for field in ("original_file_path", "patch_path", "description"):
        a, b = fm[name].get(field), om[name].get(field)
        if a != b:
            print(f"  {name}.{field}: fresh={a!r} committed={b!r}")
            diffs += 1
    if sorted(fm[name]["tags"]) != sorted(om[name]["tags"]):
        print(f"  {name}.tags: fresh={sorted(fm[name]['tags'])} committed={sorted(om[name]['tags'])}")
        diffs += 1
    fc = sorted(c.lower() for c in (fm[name].get("columns") or {}))
    oc = sorted(c.lower() for c in (om[name].get("columns") or {}))
    if fc != oc:
        print(f"  {name}.columns: fresh={fc} committed={oc}")
        diffs += 1
    fmat = (fm[name].get("config") or {}).get("materialized")
    omat = (om[name].get("config") or {}).get("materialized")
    if fmat != omat:
        print(f"  {name}.materialized: fresh={fmat!r} committed={omat!r}")
        diffs += 1

print(f"\n{diffs} difference(s) in checker-relevant fields.")

print("\n=== test node linkage (fresh) ===")
tests = [n for n in fresh["nodes"].values() if n["resource_type"] == "test"]
print(f"test nodes: {len(tests)}")
for t in tests[:3]:
    meta = t.get("test_metadata") or {}
    print(
        f"  name={meta.get('name')} column_name={t.get('column_name')!r} "
        f"attached_node={t.get('attached_node')!r} namespace={meta.get('namespace')!r}"
    )

sys.exit(0)
