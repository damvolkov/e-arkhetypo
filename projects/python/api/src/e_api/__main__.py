"""python -m e_api: dev runner — granian (Rust HTTP), ASGI interface, app-factory target, auto-reload.

`python -m e_api admin` mints the admin's key instead (`api/admin`) and prints it: shown this once."""

import asyncio
import sys

from granian import Granian
from granian.constants import Interfaces

from e_api.api.admin import mint
from infra.config.app import Env
from infra.settings import settings as st

if __name__ == "__main__":
    match sys.argv[1:]:
        case ["admin"]:
            sys.stdout.write(f"{asyncio.run(mint()).token}\n")
        case _:
            Granian(
                target="e_api.main:create_app",
                address=st.app.host,
                port=st.app.port,
                interface=Interfaces.ASGI,
                factory=True,
                ### reload is a dev convenience only: prod and local never re-import modules behind the running server.
                reload=st.app.env is Env.DEV,
            ).serve()
