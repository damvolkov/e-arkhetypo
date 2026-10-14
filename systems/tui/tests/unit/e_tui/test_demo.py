"""tests/unit/e_tui/demo: the fake app folds its pages, walks both routes and emits the blueprint it collected."""

from e_tui.app import WizardApp
from e_tui.demo import AppBlueprint, _blueprint, _result_view, build
from e_tui.models.object import Commit


def test_build_hosts_a_wizard_app_over_the_folded_pages() -> None:
    app = build()
    assert isinstance(app, WizardApp)
    assert [page.id for page in app._walk.state.graph.pages] == ["system", "db", "modules", "confirm", "report"]


def test_the_api_path_walks_every_page_and_emits_a_blueprint() -> None:
    walk = build()._walk
    walk.advance(Commit(values=("api",)))  # system: on_commit + route -> db
    assert walk.here().id == "db"
    walk.advance(Commit(values=("postgres://db",)))  # db -> modules
    assert walk.here().id == "modules"
    walk.advance(Commit(values=("rdb", "vdb")))  # modules -> confirm
    assert walk.here().id == "confirm"
    walk.advance(Commit())  # confirm -> report
    assert _blueprint(walk.state.data) == AppBlueprint(system="api", dsn="postgres://db", modules=("rdb", "vdb"))


def test_the_result_view_mounts_the_serialized_model() -> None:
    walk = build()._walk
    walk.advance(Commit(values=("api",)))
    walk.advance(Commit(values=("postgres://db",)))
    walk.advance(Commit(values=("rdb",)))
    walk.advance(Commit())
    view = list(_result_view(walk.state.data))
    assert [type(widget).__name__ for widget in view] == ["Label", "Static"]


def test_the_cli_path_skips_the_data_source_page() -> None:
    walk = build()._walk
    walk.advance(Commit(values=("cli",)))  # system: route else-branch -> modules (no dsn)
    assert walk.here().id == "modules"
    walk.advance(Commit(values=("rdb",)))
    walk.advance(Commit())
    assert _blueprint(walk.state.data) == AppBlueprint(system="cli", modules=("rdb",))
