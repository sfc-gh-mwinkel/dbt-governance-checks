"""Resolving which models a pull request actually changed."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .artifacts import Manifest, ModelNode

_YAML_SUFFIXES = (".yml", ".yaml")


class GitError(Exception):
    """Raised when git metadata required for scoping is unavailable."""


@dataclass(frozen=True)
class ChangedFiles:
    modified: frozenset[str]
    deleted: frozenset[str]

    @property
    def all(self) -> frozenset[str]:
        return self.modified | self.deleted


def _run_git(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise GitError(
            f"`git {' '.join(args)}` failed: {exc.stderr.strip() or exc.stdout.strip()}. "
            "In CI, ensure actions/checkout runs with fetch-depth: 0 so the base ref is present."
        ) from exc
    return result.stdout


def repo_root(project_dir: Path) -> Path:
    return Path(_run_git(["rev-parse", "--show-toplevel"], project_dir).strip())


def changed_files(base_ref: str, project_dir: Path) -> ChangedFiles:
    """Return files changed between base_ref and HEAD, project-relative.

    Paths are rebased onto the dbt project directory so they compare directly
    against manifest paths, which are always project-relative.
    """
    root = repo_root(project_dir)
    prefix = PurePosixPath(project_dir.resolve().relative_to(root).as_posix())

    raw = _run_git(["diff", "--name-status", f"{base_ref}...HEAD"], project_dir)

    modified: set[str] = set()
    deleted: set[str] = set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0].strip()
        # Renames report as `R100\told\tnew`; the new path is what matters.
        path = parts[-1].strip()

        relative = _rebase(path, prefix)
        if relative is None:
            continue
        if status.startswith("D"):
            deleted.add(relative)
        else:
            modified.add(relative)

    return ChangedFiles(modified=frozenset(modified), deleted=frozenset(deleted))


def _rebase(repo_relative_path: str, prefix: PurePosixPath) -> str | None:
    """Strip the project prefix, or None if the path is outside the project."""
    if str(prefix) == ".":
        return repo_relative_path
    try:
        return str(PurePosixPath(repo_relative_path).relative_to(prefix))
    except ValueError:
        return None


def select_changed_models(manifest: Manifest, changed: ChangedFiles) -> list[ModelNode]:
    """Map changed file paths onto model nodes.

    Matching patch_path as well as original_file_path is essential: removing a
    column description from a shared _models.yml must be caught even though no
    .sql file changed. Because one YAML file patches many models, a YAML edit
    correctly fans out to every model it documents.
    """
    touched = changed.all
    selected: dict[str, ModelNode] = {}

    for model in manifest.models:
        if model.original_file_path in touched or (model.patch_path and model.patch_path in touched):
            selected[model.unique_id] = model

    for model in _models_orphaned_by_deleted_yaml(manifest, changed.deleted):
        selected.setdefault(model.unique_id, model)

    return sorted(selected.values(), key=lambda m: m.unique_id)


def _models_orphaned_by_deleted_yaml(manifest: Manifest, deleted: frozenset[str]) -> list[ModelNode]:
    """Catch models left undocumented by a deleted YAML file.

    A deleted schema file no longer matches any node's patch_path, so path
    matching alone would miss the models it used to document -- the exact
    regression this gate exists to prevent. Fall back to selecting models that
    live in the deleted file's directory and now have no YAML entry.
    """
    directories = {str(PurePosixPath(path).parent) for path in deleted if PurePosixPath(path).suffix in _YAML_SUFFIXES}
    if not directories:
        return []

    return [
        model
        for model in manifest.models
        if model.patch_path is None and str(PurePosixPath(model.original_file_path).parent) in directories
    ]
