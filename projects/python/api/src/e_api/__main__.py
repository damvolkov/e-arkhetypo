"""python -m e_api: dev runner — granian (Rust HTTP), ASGI interface, app-factory target, auto-reload.

`python -m e_api admin` mints the admin's key instead (`api/admin`) and prints it: shown this once."""

import asyncio
import sys

from granian import Granian
from granian.constants import Interfaces

from e_api.api.admin import mint
from e_api.infra.config.infra import Env
from e_api.infra.settings import settings as st

if __name__ == "__main__":
    match sys.argv[1:]:
        case ["admin"]:
            issued = mint(
                dsn=st.POSTGRES_DSN,
                pool=st.POSTGRES_POOL,
                connect=st.POSTGRES_TIMEOUT,
                secret=st.AUTH_SECRET,
                ttl=st.AUTH_TTL,
                admin=st.AUTH_ADMIN,
            )
            sys.stdout.write(f"{asyncio.run(issued).token}\n")
        case _:
            Granian(
                target="e_api.main:create_app",
                address=st.APP_HOST,
                port=st.APP_PORT,
                interface=Interfaces.ASGI,
                factory=True,
                ### reload is a dev convenience only: prod and local never re-import modules behind the running server.
                reload=st.APP_ENV is Env.DEV,
            ).serve()
