"""tests/integration/e_tui/interact: a host that builds and mounts one object inside the app context.

Objects are made in `compose` (the factory runs with an active app), exactly as the real viewer builds
them — Textual widgets whose reactive setters need a running app. The mounted instance is exposed as
``app.object`` so a test can drive it through the pilot and then ask it to commit."""

from collections.abc import Callable
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widget import Widget

##### HOST #####


type Mounter = Callable[[Callable[[], Widget]], Mount]


class Mount(App[None]):
    """The minimum app that builds one object from a factory and mounts it as the whole screen."""

    def __init__(self, factory: Callable[[], Widget]) -> None:
        super().__init__()
        self._factory = factory
        ### The host exposes whichever object the factory built; the tests assert on it directly.
        self.object: Any = None

    def compose(self) -> ComposeResult:
        self.object = self._factory()
        yield self.object


@pytest.fixture
def mount() -> Mounter:
    """Wrap an object factory in the host app."""
    return Mount
