"""tests/unit/e_infra/ops/snap: GallerySnap — the matrix is the product, the shoot is a pass-through."""

from typing import TYPE_CHECKING, Any

from textual.app import App

if TYPE_CHECKING:
    from collections.abc import Callable

from e_infra.ops.snap import DEFAULT_SIZES, GallerySnap


def _apps() -> dict[str, Callable[[], App[Any]]]:
    return {"alpha": App[None], "beta": App[None]}


def test_snap_cases_are_the_full_product() -> None:
    cases = GallerySnap(("alpha", "beta")).cases()
    assert len(cases) == 2 * len(DEFAULT_SIZES)
    assert all(len(case.values) == 2 for case in cases)


def test_snap_case_ids_name_architecture_and_viewport() -> None:
    ids = [case.id for case in GallerySnap(("alpha", "beta"), sizes=((100, 30),)).cases()]
    assert ids == ["alpha-100x30", "beta-100x30"]


def test_snap_shoot_builds_the_named_app_and_returns_the_verdict() -> None:
    seen: list[tuple[Any, tuple[int, int]]] = []

    def fake_compare(app: App[object], terminal_size: tuple[int, int]) -> bool:
        seen.append((app, terminal_size))
        return True

    assert GallerySnap.shoot(fake_compare, _apps(), "alpha", (80, 24)) is True
    assert isinstance(seen[0][0], App)
    assert seen[0][1] == (80, 24)
