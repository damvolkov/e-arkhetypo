"""runtime.lifespan: one run's scope — logging routed, infra loaded, the graph sealed, every edge closed.

A cli process lives for one command, so the lifespan is one `async with`: it routes structlog to stderr
at the run's verbosity (stdout belongs to the command's output), forces the lazy infra load, writes the
`shared` and `session` sections and seals the graph before any command sees it. Edges are not opened here:
`Deps` opens each on the first ask, on this scope's exit stack, and the stack closes them in reverse."""

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from structlog.typing import BindableLogger

from e_cli.models.session import Session
from e_cli.runtime.deps import Deps
from infra.logger import logger, setup
from infra.proxy import LazyProxy
from infra.settings import Settings
from infra.settings import settings as st
from infra.state import State


##### SECTION #####
@dataclass(frozen=True, slots=True)
class SharedState:
    """The typed shared section: the two lazy singletons every command may reach through the graph."""

    settings: Settings
    logger: LazyProxy[BindableLogger]


@asynccontextmanager
async def lifespan(session: Session) -> AsyncGenerator[Deps]:
    """The run: configure logging, seal `shared` + `session` into the graph, hand the provider to the launcher."""
    setup(env=st.app.env, level=logging.DEBUG if session.verbose else logging.WARNING, stream=sys.stderr)
    state = State(shared=SharedState(settings=st, logger=logger), session=session)
    state.seal()
    logger.debug("run start", command=session.command, step="START")
    async with AsyncExitStack() as stack:
        yield Deps(stack, state)
    logger.debug("run end", command=session.command, step="STOP")
