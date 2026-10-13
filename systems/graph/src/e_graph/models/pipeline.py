"""models.pipeline: how the API names a pipeline in its list — the id to address it, the line that says what it is."""

import msgspec


class PipelineInfo(msgspec.Struct, frozen=True, kw_only=True):
    """One available pipeline: `id` is its module name under `pipelines/`, `summary` its docstring headline."""

    id: str
    summary: str = ""
    nodes: int = 0
