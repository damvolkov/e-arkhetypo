"""ops/snap: GallerySnap — the snapshot gallery for any set of Textual architectures.

Wraps `pytest-textual-snapshot`: register architecture *names* and viewports, get one clean test id per
pair; the apps themselves arrive at run time through a fixture mapping (collection cannot import them).
Usage, in a test module beside a conftest holding ``apps: dict[str, Callable[[], App]]``:

    _CASES = GallerySnap(("standard", "curves")).cases()

    @pytest.mark.parametrize(("name", "size"), _CASES)
    def test_gallery(snap_compare, apps, name, size):
        assert GallerySnap.shoot(snap_compare, apps, name, size)

Accepting a snapshot is a human act: ``--snapshot-update`` regenerates the SVGs under ``__snapshots__``,
review the diff, commit. The gate then fails on any visual drift. Materialized only into tui services
(api and cli exclude this file at materialize time)."""

from typing import TYPE_CHECKING, Final, Protocol

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from _pytest.mark.structures import ParameterSet
    from textual.app import App

##### DEFAULTS #####
DEFAULT_SIZES: Final[tuple[tuple[int, int], ...]] = ((80, 24), (140, 50))


class SnapCompare(Protocol):
    """The ``snap_compare`` fixture of pytest-textual-snapshot: render an app at a size, compare it to the stored snapshot."""

    def __call__(self, app: App[None], *, terminal_size: tuple[int, int]) -> bool: ...


class GallerySnap:
    """The cartesian product of architecture names and viewports, as pytest parameters."""

    def __init__(self, names: Iterable[str], sizes: Sequence[tuple[int, int]] = DEFAULT_SIZES) -> None:
        self._names = tuple(names)
        self._sizes = tuple(sizes)

    @staticmethod
    def shoot(
        snap_compare: SnapCompare, apps: Mapping[str, Callable[[], App[None]]], name: str, size: tuple[int, int]
    ) -> bool:
        """Build the named architecture fresh and compare its render against the stored snapshot."""
        return snap_compare(apps[name](), terminal_size=size)

    ############################################################

    ##### PUBLIC #####

    def cases(self) -> list[ParameterSet]:
        """One param per (architecture, size), id `<name>-<w>x<h>`."""
        return [
            pytest.param(name, size, id=f"{name}-{size[0]}x{size[1]}") for name in self._names for size in self._sizes
        ]
