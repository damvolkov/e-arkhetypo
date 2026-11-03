"""ports/llm: a chat model answering under a JSON schema — the decoded object, valid against it."""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Mapping


@runtime_checkable
class LlmPort(Provider, Protocol):
    """`model` names the model that answers. A reply cut at the output ceiling raises `TruncatedError`, one outside the
    contract `ModelError`."""

    @property
    def model(self) -> str: ...

    async def structured(self, system: str, prompt: str, schema: Mapping[str, Any]) -> Any: ...
