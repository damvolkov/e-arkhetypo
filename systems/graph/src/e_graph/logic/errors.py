"""logic.errors: what the DARTS engine raises, one section per piece — the subclass says which side failed.

Every output failure carries its trace — the last raw reply, the attempts, what they cost and the
provider's finish reason — in its attributes and in its message, so a failed node's span and log line
say exactly what happened without a debugger. The discovery's failures are `RuleError`s, one per broken
law, grouped per section in a `CatalogError` — every violation reported at once, never the first alone."""

from enum import StrEnum, auto
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from e_graph.logic.models import Usage


##### AGENT #####
class AgentError(Exception):
    """Anything the agent could not do."""


class SchemaError(AgentError):
    """The output asked is no shape the agent knows: a pydantic model, a msgspec Struct, a dataclass or a JSON Schema."""


class EndpointError(AgentError):
    """Nothing to connect with: a tier without settings, a CUSTOM endpoint without a base, a missing key."""


class ProviderError(AgentError):
    """The provider failed the call: transport, authentication, quota, a server error."""


class OutputError(AgentError):
    """The model answered, but never the shape asked; the subclass says why, the attributes say how."""

    def __init__(self, message: str, *, raw: str, attempts: int, usage: Usage, finish: str) -> None:
        self.raw, self.attempts, self.usage, self.finish = raw, attempts, usage, finish
        trace = f"finish={finish or 'none'}, attempts={attempts}, output_tokens={usage.output_tokens}"
        super().__init__(f"{message} [{trace}]")


class InvalidError(OutputError):
    """Every reply broke the shape: retries spent, the last validation error in the message."""


class TruncatedError(OutputError):
    """The reply was cut at the token limit and no larger budget was left to ask for."""


class RefusedError(OutputError):
    """The provider refused or filtered the reply: asking again cannot change it."""


##### DISCOVER #####
class Rule(StrEnum):
    """Each law a pipeline's specs and runners are judged by."""

    TREE = auto()
    DECODE = auto()
    MERGE = auto()
    FILENAME = auto()
    DEPENDS = auto()
    FALLBACK = auto()
    CYCLE = auto()
    RUNNER = auto()
    ORPHAN = auto()
    HOOK = auto()
    SIGNATURE = auto()
    DOC = auto()
    WIKI = auto()


class RuleError(ValueError):
    """One broken law: which `rule`, the `subject` (a file, a spec, a function) and what is wrong with it."""

    def __init__(self, rule: Rule, subject: str, detail: str) -> None:
        self.rule, self.subject, self.detail = rule, subject, detail
        super().__init__(f"[{rule}] {subject}: {detail}")


class CatalogError(ExceptionGroup[RuleError]):
    """Every law one section (or the pipeline's tree) breaks, together: a section is fixed in one pass, not one by one."""

    @property
    def breaches(self) -> tuple[RuleError, ...]:
        """The broken laws, flat: a catalog group never nests."""
        return cast("tuple[RuleError, ...]", self.exceptions)


class AuditError(ExceptionGroup[CatalogError]):
    """Every incoherent part of a pipeline — its tree and each broken section — from one audit."""

    @property
    def catalogs(self) -> tuple[CatalogError, ...]:
        """One group per incoherent part, flat."""
        return cast("tuple[CatalogError, ...]", self.exceptions)
