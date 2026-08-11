"""Changed-model resolution."""

from __future__ import annotations

from pathlib import PurePosixPath

from conftest import make_manifest, make_model

from dbt_governance.changed import ChangedFiles, _rebase, select_changed_models


def _changed(modified=(), deleted=()) -> ChangedFiles:
    return ChangedFiles(modified=frozenset(modified), deleted=frozenset(deleted))


def test_rebase_strips_project_prefix():
    assert _rebase("transform/models/a.sql", PurePosixPath("transform")) == "models/a.sql"


def test_rebase_returns_none_outside_project():
    assert _rebase("docs/readme.md", PurePosixPath("transform")) is None


def test_rebase_is_identity_at_repo_root():
    assert _rebase("models/a.sql", PurePosixPath(".")) == "models/a.sql"


def test_sql_change_selects_its_model():
    model = make_model(name="dim_a", path="models/marts/dim_a.sql")
    manifest = make_manifest([model, make_model(name="dim_b", path="models/marts/dim_b.sql")])
    selected = select_changed_models(manifest, _changed(modified=["models/marts/dim_a.sql"]))
    assert [m.name for m in selected] == ["dim_a"]


def test_yaml_change_fans_out_to_every_model_it_documents():
    """Removing a column description from a shared schema file must be caught
    even though no .sql file changed."""
    shared = "models/marts/_models.yml"
    manifest = make_manifest(
        [
            make_model(name="dim_a", path="models/marts/dim_a.sql", patch_path=shared),
            make_model(name="dim_b", path="models/marts/dim_b.sql", patch_path=shared),
            make_model(name="dim_c", path="models/other/dim_c.sql", patch_path="models/other/_models.yml"),
        ]
    )
    selected = select_changed_models(manifest, _changed(modified=[shared]))
    assert [m.name for m in selected] == ["dim_a", "dim_b"]


def test_unchanged_models_are_not_selected():
    manifest = make_manifest([make_model(name="dim_a", path="models/marts/dim_a.sql")])
    assert select_changed_models(manifest, _changed(modified=["README.md"])) == []


def test_deleted_yaml_selects_models_it_left_undocumented():
    """A deleted schema file matches no node's patch_path, so path matching
    alone would miss the models it used to document."""
    manifest = make_manifest(
        [
            make_model(name="dim_a", path="models/marts/dim_a.sql", patch_path=None),
            make_model(name="dim_far", path="models/other/dim_far.sql", patch_path=None),
        ]
    )
    selected = select_changed_models(manifest, _changed(deleted=["models/marts/_models.yml"]))
    assert [m.name for m in selected] == ["dim_a"]


def test_deleted_yaml_does_not_reselect_still_documented_models():
    manifest = make_manifest(
        [make_model(name="dim_a", path="models/marts/dim_a.sql", patch_path="models/marts/_other.yml")]
    )
    assert select_changed_models(manifest, _changed(deleted=["models/marts/_models.yml"])) == []


def test_model_selected_once_when_both_sql_and_yaml_change():
    model = make_model(name="dim_a", path="models/marts/dim_a.sql", patch_path="models/marts/_models.yml")
    manifest = make_manifest([model])
    selected = select_changed_models(
        manifest, _changed(modified=["models/marts/dim_a.sql", "models/marts/_models.yml"])
    )
    assert [m.name for m in selected] == ["dim_a"]
