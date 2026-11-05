"""python -m e_graph: dev runner — granian (Rust HTTP), ASGI interface, app-factory target, auto-reload."""

from granian import Granian
from granian.constants import Interfaces

from e_graph.api.router.ui import UI
from infra.config.infra import Env
from infra.settings import settings as st

if __name__ == "__main__":
    Granian(
        target="e_graph.main:create_app",
        address=st.APP_HOST,
        port=st.APP_PORT,
        interface=Interfaces.ASGI,
        factory=True,
        ### reload is a dev convenience only: prod and local never re-import modules behind the running server.
        reload=st.APP_ENV is Env.DEV,
        ### the canvas is TypeScript and its bundle is read per request: neither is a reason to restart Python.
        reload_ignore_paths=[UI],
    ).serve()
