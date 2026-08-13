# Setup

Installing the governance gate in a dbt Core repository.

---

## Prerequisites

| Requirement | Why | Confirm before starting |
| --- | --- | --- |
| dbt Core 1.7-1.9 | Manifest schema v7-v20 is supported; the tool errors rather than misread an untested version | `dbt --version` |
| Python 3.9+ | | `python3 --version` |
| dbt Hub reachable, or vendored packages | `dbt deps` runs before parse | `dbt deps` from the VDI |
| Snowflake CI credentials | Only for the column completeness check | Existing CI secrets |
| `fetch-depth: 0` in checkout | Change scoping needs the base ref locally | Workflow config |

If dbt Hub is blocked from the VDI, either vendor `dbt_packages/` into the repo or point `packages.yml` at an internal mirror. `dbt deps` failing stops everything downstream.

---

**Repository references.** The snippets below point at `sfc-gh-mwinkel/dbt-governance-checks`, where this tool is currently hosted. When it is transferred into the client's own organization, update the `uses:` line, the `pip install git+...` URL, and the `governance-repo` default in `governance-check.yml` to the new owner.

**Private repositories.** If this repo stays private, calling its reusable workflow from another repo requires Actions access to be granted: on this repo, Settings, Actions, General, "Access", set to allow access from repositories in the same organization. Without that, the caller fails with a workflow-not-found error. Path A (`pip install git+...`) needs a token with read access instead.

---

## Which integration path

Completeness checking needs `catalog.json`, which needs models **built**. That makes the job sequence `dbt deps` → `dbt build` → `dbt docs generate` → check.

If your repo already has a slim CI job that builds changed models, that sequence is already most of the way there.

| | Step in existing slim CI | Standalone workflow |
| --- | --- | --- |
| Builds models twice | No | Yes |
| Extra Snowflake credential path | No | Yes |
| Setup effort | Add ~15 lines | Add ~10 lines |
| Works with no existing pipeline | No | Yes |

**Prefer path A** if a slim CI pipeline exists. A second build doubles CI cost and creates another credential path for security review.

---

## Path A: a step in an existing slim CI job

Add to the job that already runs `dbt build` on changed models, after the build step:

```yaml
      # catalog.json is the only source of the columns a model actually
      # returns, so completeness cannot be checked without this step.
      - name: dbt docs generate
        run: dbt docs generate --target ci
        continue-on-error: true

      - name: Install the governance checker
        run: pip install "git+https://github.com/sfc-gh-mwinkel/dbt-governance-checks@v1.0.0"

      - name: Governance annotations
        continue-on-error: true
        run: dbt-governance --changed-only --base-ref "origin/${{ github.base_ref }}" --format annotations

      - name: Governance check
        run: |
          dbt-governance \
            --changed-only \
            --base-ref "origin/${{ github.base_ref }}" \
            --format markdown \
            --output "${RUNNER_TEMP}/governance.md"
          cat "${RUNNER_TEMP}/governance.md" >> "$GITHUB_STEP_SUMMARY"
```

`continue-on-error: true` on `dbt docs generate` is deliberate. If the catalog cannot be produced, the checker reports `DOC009` for each affected model rather than the workflow dying with an opaque dbt error.

Running the checker twice is also deliberate: the first pass emits inline annotations and is allowed to fail, the second produces the summary and sets the exit code.

Ensure the job's checkout uses `fetch-depth: 0`.

---

## Path B: standalone reusable workflow

Add `.github/workflows/governance.yml` to the dbt repo:

```yaml
name: dbt governance

on:
  pull_request:
    branches: [main]

jobs:
  governance:
    uses: sfc-gh-mwinkel/dbt-governance-checks/.github/workflows/governance-check.yml@v1.0.0
    with:
      project-dir: "."
      changed-only: true
      # Set this when requirements.txt lives at the repo root but the dbt
      # project is in a subdirectory. Resolved relative to project-dir.
      # requirements-file: "../requirements.txt"
      # Set this only if profiles.yml is somewhere dbt would not find on its
      # own. dbt already checks the project directory, then ~/.dbt.
      # profiles-dir: "."
    secrets:
      SNOWFLAKE_ACCOUNT: ${{ secrets.SNOWFLAKE_ACCOUNT }}
      SNOWFLAKE_USER: ${{ secrets.SNOWFLAKE_USER }}
      SNOWFLAKE_ROLE: ${{ secrets.SNOWFLAKE_ROLE }}
      SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
      SNOWFLAKE_DATABASE: ${{ secrets.SNOWFLAKE_DATABASE }}
      DBT_ENV_SECRET_PRIVATE_KEY: ${{ secrets.DBT_ENV_SECRET_PRIVATE_KEY }}
```

### Workflow inputs

| Input | Default | Notes |
| --- | --- | --- |
| `project-dir` | `.` | Directory containing `dbt_project.yml` |
| `rules-file` | `governance_rules.yml` | Relative to `project-dir` |
| `requirements-file` | `requirements.txt` | Relative to `project-dir`. dbt must come from here |
| `profiles-dir` | unset | Only needed if dbt cannot resolve `profiles.yml` itself |
| `changed-only` | `true` | Scope to models changed against the PR base |
| `skip-catalog` | `false` | Skip the build; disables completeness checking |
| `warnings-as-errors` | `false` | Fail on warnings too |
| `dbt-target` | `ci` | Target in `profiles.yml` |
| `python-version` | `3.11` | |
| `governance-repo` / `governance-ref` | this repo / `v1.0.0` | Where to fetch the checker from |

Pinning `@v1.0.0` means fixes arrive by bumping a tag, with no vendored code to re-copy.

### Running with no warehouse access

Set `skip-catalog: true` to run only the rules that need no warehouse (all tag rules, plus every documentation rule except `DOC004`). Set `require_all_columns_documented` to `severity: ignore` in the rules file so it does not report `DOC009` for every model.

This is a reasonable first step if warehouse credentials in CI need a longer security review, but it does not close the undocumented-column loophole.

---

## Rollout

Turning every rule on at once against a mature project produces an unpassable PR gate. Recommended sequence:

**1. Measure.** Run against the whole project locally and count the backlog:

```bash
dbt-governance --project-dir . --format console | tail -1
```

**2. Land in warning mode.** Set every rule to `severity: warning` and merge. The check runs and reports but cannot block, which surfaces the backlog without stopping delivery.

**3. Gate new work.** Keep `--changed-only` on and promote rules to `error` one at a time. Because scoping is per-PR, existing violations do not block anyone until the file is touched.

**4. Exempt what is genuinely deferred.** Use dated exemptions with a ticket reference in `reason`. The expiry forces the conversation again rather than letting it lapse.

Suggested promotion order, cheapest to fix first: `DOC001` and `DOC002` (a missing YAML entry is a one-line fix), then `TAG001` and `TAG002`, then `DOC005` through `DOC007`, then `DOC008`, and `DOC004` last since it is usually the largest backlog.

**5. Make it required.** Once errors are clean, mark the check required in branch protection. Until that point the gate is advisory.

---

## Verifying the installation

```bash
# 1. Rules file parses and severities are valid
dbt parse
dbt-governance --project-dir . --format console

# 2. Change scoping resolves the base ref
git fetch origin main
dbt-governance --project-dir . --changed-only --base-ref origin/main

# 3. Confirm the gate actually fails
#    Delete a column description, then re-run. `dbt parse` is required first:
#    the checker reads artifacts, so the edit is invisible until the manifest
#    is regenerated. Expect exit code 1.
dbt parse && dbt-governance --project-dir . --changed-only --base-ref origin/main
```

A clean pass on a project you know to be non-compliant means something is misconfigured. The most common cause is `require_all_columns_documented` reporting `DOC009` because `dbt docs generate` never ran.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Checks pass despite a violation you just introduced | Stale `manifest.json` | Re-run `dbt parse`. The checker reads artifacts, not source files, so an edit is invisible until the manifest is regenerated. CI always parses the PR head, so this only bites locally. |
| `dbt docs generate is not supported` | Running dbt Fusion 2.x rather than dbt Core | Use `dbt compile --write-catalog`. dbt Core 1.7-1.9 still uses `dbt docs generate`, which is what the shipped workflow calls. |
| `manifest schema vNN has not been validated` | dbt version outside the tested range | Confirm the dbt version, then widen `MAX_MANIFEST_SCHEMA` in `artifacts.py` after checking field locations |
| `DOC009` on every model | No `catalog.json` | Run `dbt docs generate`, or set the rule to `severity: ignore` |
| `DOC009` on a few models | Those models were not built | Check the build step; `--select state:modified+` may have excluded them |
| `git ... failed` | Shallow clone | `fetch-depth: 0` on checkout |
| Zero models checked | Project prefix mismatch | Pass `--project-dir` pointing at the directory containing `dbt_project.yml` |
| Package models reported | Should not happen | Confirm `metadata.project_name` in the manifest; only first-party models are checked |
| Every model fails `TAG002` | Vocabulary does not match real tags | Add operational tags to `additional_allowed_tags`, or set `allowed_only: false` |
| `dbt: command not found`, or the "Verify dbt is available" step fails | dbt is not in the requirements file the workflow installed | Point `requirements-file` at the file that pins dbt; it is resolved relative to `project-dir` |
| `Could not find profile` | dbt cannot locate `profiles.yml` | Set the `profiles-dir` input, relative to `project-dir` |

---

## Appendix: what a pre-commit rollout would involve

The gate runs in CI only. Pre-commit was considered and deferred; this records why, so the decision can be revisited on purpose.

To adopt pre-commit you would need:

- `pip install pre-commit` on every developer machine in the VDI
- each developer running `pre-commit install` once, per clone
- `.pre-commit-config.yaml` committed to the dbt repo
- pre-commit fetching hook environments over the network on first run

Three reasons CI came first:

1. **Git hooks are not committed to the repo.** The per-developer install step cannot be enforced centrally, and you cannot tell who skipped it. Coverage is invisible.
2. **It is not an enforcement boundary.** `git commit --no-verify` bypasses it. Only CI can actually block a merge.
3. **The strongest rule cannot run there anyway.** `DOC004` needs a built warehouse. Pre-commit could only run the tag rules and description-quality checks.

Its real benefit is fast local feedback, and that remains available: the checker is a plain CLI with no Actions-specific logic in its core, so developers can run it directly before pushing:

```bash
dbt parse
dbt-governance --changed-only --base-ref origin/main
```

If you later want the framework, add `.pre-commit-config.yaml` to the dbt repo:

```yaml
repos:
  - repo: local
    hooks:
      - id: dbt-governance
        name: dbt governance checks
        entry: dbt-governance --changed-only --base-ref origin/main
        language: system
        pass_filenames: false
```

No changes to this tool are required.
