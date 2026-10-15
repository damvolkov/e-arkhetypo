"""models.pipeline: how the API names a pipeline in its list — the id to address it, the line that says what it is."""

from typing import Any

import msgspec


class PipelineInfo(msgspec.Struct, frozen=True, kw_only=True):
    """One available pipeline: `id` is its module name under `pipelines/`, `summary` its docstring headline,
    `seed` the run data it expects — the paths of its sample documents, ready to run out of the box."""

    id: str
    summary: str = ""
    nodes: int = 0
    seed: dict[str, Any] = msgspec.field(default_factory=dict)
