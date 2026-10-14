"""core/settings/darts: the DARTS orchestrator — how much of a section runs at once, and how semantic specs fuse (DARTS_*)."""

from datetime import timedelta

from pydantic import Field

from e_core.core.settings.base import BaseSettings


class DartsSettings(BaseSettings):
    """DARTS_CONCURRENCY — deterministic specs of one step in flight; DARTS_CALLS — fused agent calls of one step
    in flight; DARTS_FUSION_SPECS — most specs one fused call answers; DARTS_FUSION_TOKENS — most estimated
    tokens (instructions, wiki, examples, material, schema) one fused call carries, a bigger group splits in
    calls; DARTS_TIMEOUT — a spec's deadline when its own `timeout` is unset (a fused call takes the longest of
    its specs')."""

    darts_concurrency: int = Field(default=8, ge=1)
    darts_calls: int = Field(default=4, ge=1)
    darts_fusion_specs: int = Field(default=8, ge=1)
    darts_fusion_tokens: int = Field(default=8000, ge=256)
    darts_timeout: timedelta = timedelta(seconds=120)
