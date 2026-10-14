"""python -m e_graph: dev runner — granian (Rust HTTP), ASGI interface, app-factory target, auto-reload."""

from granian import Granian
from granian.constants import Interfaces

from core.settings import settings as st
from core.settings.app import Env
from e_graph.api.router.ui import UI

if __name__ == "__main__":
    Granian(
        target="e_graph.main:create_app",
        address=st.app.app_host,
        port=st.app.app_port,
        interface=Interfaces.ASGI,
        factory=True,
        ### reload is a dev convenience only: prod and local never re-import modules behind the running server.
        reload=st.app.app_env is Env.DEV,
        ### the canvas is TypeScript and its bundle is read per request: neither is a reason to restart Python.
        reload_ignore_paths=[UI],
    ).serve()
