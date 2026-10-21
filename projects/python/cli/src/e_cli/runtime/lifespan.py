"""runtime.lifespan: one run's scope — logging routed, core loaded, the graph sealed, every edge closed.

A cli process lives for one command, so the lifespan is one `async with`: it routes structlog to stderr
at the run's verbosity (stdout belongs to the command's output), forces the lazy core load, writes the
`core` and `session` sections and seals the graph before any command sees it. Edges are not opened here:
`Deps` opens each on the first ask, on this scope's exit stack, and the stack closes them in reverse."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from structlog.typing import BindableLogger

from core.logger import logger, setup
from core.proxy import LazyProxy
from core.settings import Settings
from core.settings import settings as st
from core.state import State
from e_cli.models.session import Session
from e_cli.runtime.deps import Deps


##### SECTION #####
@dataclass(frozen=True, slots=True)
class CoreState:
    """The typed core section: the two lazy singletons every command may reach through the graph."""

    settings: Settings
    logger: LazyProxy[BindableLogger]


@asynccontextmanager
async def lifespan(session: Session) -> AsyncIterator[Deps]:
    """The run: configure logging, seal `core` + `session` into the graph, hand the provider to the launcher."""
    setup(env=st.app.app_env, level=logging.DEBUG if session.verbose else logging.WARNING, stream=sys.stderr)
    state = State(core=CoreState(settings=st, logger=logger), session=session)
    state.seal()
    logger.debug("run start", command=session.command, step="START")
    async with AsyncExitStack() as stack:
        yield Deps(stack, state)
    logger.debug("run end", command=session.command, step="STOP")
