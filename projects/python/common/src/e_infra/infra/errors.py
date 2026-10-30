"""infra/errors: typed exception hierarchy — every domain exception inherits from CoreError."""


##### ROOT #####
class CoreError(Exception):
    """All e-core exceptions inherit from this root."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


##### PROVIDERS #####
class ProviderError(CoreError):
    """A provider failed at its border: what a third-party library raised, or a call on a provider that is not open.

    Providers translate the exceptions of their library into this tree; no upper layer imports a library's own."""


class DatabaseError(ProviderError):
    """A database that cannot be reached, or refuses a statement."""


class StoreError(ProviderError):
    """A key-value store that cannot be reached."""


class HttpError(ProviderError):
    """An HTTP exchange that failed: unreachable, a non-2xx answer (its `status`), or a body that is not JSON."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class HttpTimeoutError(HttpError, TimeoutError):
    """An HTTP exchange that outlasted its bound, headers or body."""


class QueueError(ProviderError):
    """A durable queue that cannot be reached: the work falls back to memory."""


class ParseError(ProviderError):
    """A document, page or web page a reader could not read."""


class ModelError(ProviderError):
    """A model that answered nothing usable: refused an item, or spoke outside the contract."""


class TruncatedError(ModelError):
    """The model's answer hit its output ceiling before it was whole: asking for less in one call fixes it."""
