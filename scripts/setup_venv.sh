#!/usr/bin/env bash
# Create a virtual environment pinned to the dbt version the client runs.
#
# Why this exists: a globally installed `dbt` may be a different distribution
# entirely. dbt Fusion 2.x, for instance, has no `dbt docs generate` -- so
# fixtures regenerated with it would not prove the shipped CI workflow works.
# This venv pins dbt Core 1.9, which is what the target environment runs.
#
# The venv shadows any global dbt only while activated, so it is safe to keep
# alongside another dbt installation.
#
# Usage:
#   scripts/setup_venv.sh            # default Python
#   scripts/setup_venv.sh python3.11 # specific interpreter

set -euo pipefail

PYTHON="${1:-python3}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${REPO_ROOT}/.venv"

if ! command -v "${PYTHON}" >/dev/null 2>&1; then
  echo "error: ${PYTHON} not found on PATH" >&2
  exit 2
fi

# dbt Core 1.9 supports Python 3.9 through 3.12.
"${PYTHON}" - <<'PY'
import sys
major, minor = sys.version_info[:2]
if not (major == 3 and 9 <= minor <= 12):
    sys.exit(
        f"error: dbt Core 1.9 requires Python 3.9-3.12, found {major}.{minor}. "
        "Pass a supported interpreter, e.g. scripts/setup_venv.sh python3.11"
    )
PY

echo "Creating ${VENV} with $("${PYTHON}" --version)..."
"${PYTHON}" -m venv "${VENV}"

"${VENV}/bin/python" -m pip install --upgrade pip --quiet
"${VENV}/bin/pip" install --quiet -r "${REPO_ROOT}/requirements.txt" -r "${REPO_ROOT}/requirements-dev.txt"

echo
"${VENV}/bin/dbt" --version 2>&1 | head -4
echo
cat <<EOF
Ready. Either activate the environment:

  source .venv/bin/activate
  dbt --version
  pytest tests/ -q

or call it directly without activating:

  .venv/bin/dbt --version
  .venv/bin/pytest tests/ -q

scripts/rebuild_fixture.sh picks up .venv/bin/dbt automatically.
EOF
