"""infra/payload: the one JSON value of the tree — a body, a schema, a model's answer, a parsed document, a compose file."""

from collections.abc import Mapping, Sequence

type JSON = str | int | float | bool | Mapping[str, JSON] | Sequence[JSON] | None
