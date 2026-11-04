"""infra/config/darts: the DARTS orchestrator — how much of a section runs at once, how semantic specs fuse."""

from datetime import timedelta
from typing import Annotated

from pydantic import Field, PositiveInt

from e_infra.infra.config.base import BaseSettings


##### SETTINGS #####
class DartsSettings(BaseSettings):
    """DARTS: concurrency of the deterministic specs, fusion of the semantic ones into agent calls."""

    ### deterministic specs of one step in flight.
    DARTS_CONCURRENCY: PositiveInt = 8
    ### fused agent calls of one step in flight.
    DARTS_CALLS: PositiveInt = 4
    ### most specs one fused call answers.
    DARTS_FUSION_SPECS: PositiveInt = 8
    ### most estimated tokens (instructions, wiki, examples, material, schema) one fused call carries; a bigger group splits.
    DARTS_FUSION_TOKENS: Annotated[int, Field(ge=256)] = 8000
    ### a spec's deadline when its own `timeout` is unset (a fused call takes the longest of its specs').
    DARTS_TIMEOUT: timedelta = timedelta(seconds=120)
