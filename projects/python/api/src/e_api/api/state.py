"""api.state: Litestar's application state, typed — one entry, the system graph every lifespan fills and seals.

Litestar owns `app.state` and types it as its own `State`; replacing it with another class breaks that
contract and forces a cast at every read. Instead `AppState` *is* a Litestar `State`, handed to the
constructor, holding one typed entry: `system`, the core `State` graph (auto-vivifying while the
lifespans build it, sealed once they are done). Litestar itself builds this class wherever a
dependency annotates the reserved `state: AppState` — HTTP and websocket alike — and lifespans,
which receive the app, narrow it with `AppState.of(app)`: a runtime check, never a cast."""

from litestar import Litestar
from litestar.datastructures import State as LitestarState

from core.state import State


class AppState(LitestarState):
    """Litestar's state narrowed to what this app keeps in it: the sealed system graph."""

    __slots__ = ()

    system: State

    @classmethod
    def of(cls, app: Litestar) -> AppState:
        """The app's state as this class — `create_app` installs it, so anything else is a wiring bug."""
        match app.state:
            case AppState() as state:
                return state
            case other:
                msg = f"app.state is {type(other).__name__}, not AppState: create_app owns the state"
                raise TypeError(msg)
