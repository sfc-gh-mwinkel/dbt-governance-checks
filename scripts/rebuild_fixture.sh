#!/usr/bin/env bash
# Rebuild the fixture artifacts: manifest.json from `dbt parse`, and
# catalog.json from a real warehouse build.
#
# The catalog is the only source of a model's actual columns, so it cannot be
# produced without building. Everything else runs offline.
#
# Usage:
#   scripts/rebuild_fixture.sh parse                 # manifest only, no warehouse
#   scripts/rebuild_fixture.sh build <connection>    # manifest + real catalog
#
# <connection> is a Snowflake CLI connection name from ~/.snowflake/connections.toml.

set -euo pipefail

MODE="${1:-parse}"
CONNECTION="${2:-}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${REPO_ROOT}/fixtures/dbt_project"
DATABASE="${SNOWFLAKE_DATABASE:-DBT_GOVERNANCE_FIXTURE}"

# dim_not_built is deliberately never built: its absence from the catalog is
# what exercises DOC009. Do not remove this exclusion.
EXCLUDE_FROM_BUILD="dim_not_built"

cd "${PROJECT_DIR}"

if [[ "${MODE}" == "build" ]]; then
  if [[ -z "${CONNECTION}" ]]; then
    echo "error: build mode needs a connection name, e.g. scripts/rebuild_fixture.sh build personal_sandbox" >&2
    exit 2
  fi

  # Read credentials from the Snowflake CLI config and export them for dbt.
  # Values are never printed.
  eval "$(python3 - "${CONNECTION}" "${DATABASE}" <<'PY'
import pathlib, shlex, sys, tomllib

name, database = sys.argv[1], sys.argv[2]
config = tomllib.loads((pathlib.Path.home() / ".snowflake" / "connections.toml").read_text())
if name not in config:
    sys.exit(f"error: connection {name!r} not found in ~/.snowflake/connections.toml")

connection = config[name]
env = {
    "SNOWFLAKE_ACCOUNT": connection["account"],
    "SNOWFLAKE_USER": connection["user"],
    "SNOWFLAKE_ROLE": connection.get("role", "ACCOUNTADMIN"),
    "SNOWFLAKE_WAREHOUSE": connection.get("warehouse", "COMPUTE_WH"),
    "SNOWFLAKE_DATABASE": database,
    "SNOWFLAKE_SCHEMA": "MAIN",
}
key_path = connection.get("private_key_path")
if key_path:
    env["SNOWFLAKE_PRIVATE_KEY_PATH"] = str(pathlib.Path(key_path).expanduser())
elif connection.get("password"):
    env["SNOWFLAKE_PASSWORD"] = connection["password"]

print("export " + " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items()))
PY
)"

  echo "Ensuring ${DATABASE} exists..."
  snow sql -c "${CONNECTION}" -q \
    "create database if not exists ${DATABASE} comment='Fixture for dbt-governance-checks; safe to drop';" >/dev/null

  export DBT_PROFILES_DIR=.
  dbt seed --target sandbox
  dbt run --target sandbox --exclude "${EXCLUDE_FROM_BUILD}"

  # dbt Core 1.7-1.9 uses `dbt docs generate`; dbt Fusion 2.x replaced it with
  # `dbt compile --write-catalog`. Try the modern form, fall back to the older.
  if ! dbt compile --write-catalog --target sandbox 2>/dev/null; then
    dbt docs generate --target sandbox
  fi

  cp target/catalog.json "${REPO_ROOT}/fixtures/catalog.json"
  echo "Updated fixtures/catalog.json from a real build."
fi

# Always regenerate the manifest from the credential-free ci target, so the
# committed fixture matches what CI parses.
DBT_PROFILES_DIR=. dbt parse --target ci
cp target/manifest.json "${REPO_ROOT}/fixtures/manifest.json"
echo "Updated fixtures/manifest.json from dbt parse."

python3 "${REPO_ROOT}/scripts/check_fixture_drift.py"

echo
echo "Now re-check the expectations in tests/test_golden.py, then run:"
echo "  python -m pytest tests/ -q"
