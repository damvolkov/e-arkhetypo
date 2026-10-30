"""infra/config/darts: the DARTS orchestrator — how much of a section runs at once, how semantic specs fuse (DARTS_*)."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class DartsSettings(BaseSettings):
    """DARTS_CONCURRENCY — deterministic specs of one step in flight; DARTS_CALLS — fused agent calls of one step
    in flight; DARTS_FUSION_SPECS — most specs one fused call answers; DARTS_FUSION_TOKENS — most estimated
    tokens (instructions, wiki, examples, material, schema) one fused call carries, a bigger group splits in
    calls; DARTS_TIMEOUT — a spec's deadline when its own `timeout` is unset (a fused call takes the longest of
    its specs')."""

    model_config = SettingsConfigDict(env_prefix="DARTS_")

    concurrency: int = Field(default=8, ge=1)
    calls: int = Field(default=4, ge=1)
    fusion_specs: int = Field(default=8, ge=1)
    fusion_tokens: int = Field(default=8000, ge=256)
    timeout: timedelta = timedelta(seconds=120)
