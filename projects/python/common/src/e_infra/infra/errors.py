"""infra/errors: the one root of every error — each layer imports its exceptions from here, none defines its own.

`CoreError` is the root. Four branches hang from it, one per kind of module: `ProviderError` (a provider failed at its
border), `EngineError`, `ProcessorError` and `OpsError`. Providers translate the exceptions of their library into the
provider branch; no upper layer imports a library's own.

A provider fails as a **driver** (`DriverError`: a system outside the process) or as an **adapter** (`AdapterError`: a
library inside it). A capability met on both natures raises an error that is honestly both: `CacheError` (theine in
memory, Postgres over the wire) and `DocumentError` (docling-serve over HTTP, docling in process) inherit
`DriverError` and `AdapterError` at once, so `except DriverError` and `except AdapterError` each catch the failure of
the nature they guard."""

from enum import StrEnum


##### ROOT #####
class CoreError(Exception):
    """All e-core exceptions inherit from this root."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


##### PROVIDERS #####
class ProviderError(CoreError):
    """A provider failed at its border: what a third-party library raised, or a call on a provider that is not open."""


class DriverError(ProviderError):
    """A system outside the process failed: unreachable, refusing, slow, or answering outside its contract."""


class AdapterError(ProviderError):
    """A library inside the process failed: it refused its input, or the provider it wraps is not open."""


class DatabaseError(DriverError):
    """A database that cannot be reached, or refuses a statement."""


class StoreError(DriverError):
    """A key-value store that cannot be reached."""


class QueueError(DriverError):
    """A durable queue that cannot be reached: the work falls back to memory."""


class HttpError(DriverError):
    """An HTTP exchange that failed: unreachable, a non-2xx answer (its `status`), or a body that is not JSON."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class HttpTimeoutError(HttpError, TimeoutError):
    """An HTTP exchange that outlasted its bound, headers or body."""


class TelemetryError(DriverError):
    """A tracer that is not open, or whose collector cannot be reached."""


class ModelError(DriverError):
    """A model server that answered nothing usable: refused an item, or spoke outside the contract."""


class TruncatedError(ModelError):
    """The model's answer hit its output ceiling before it was whole: asking for less in one call fixes it."""


class ParseError(AdapterError):
    """A document, page or web page an in-process reader could not read."""


class CacheError(DriverError, AdapterError):
    """A cache that is not open, or whose backend failed — the capability is met in memory and over the wire."""


class DocumentError(DriverError, AdapterError):
    """A document conversion that failed — the capability is met by a server and by a library in process."""


##### ENGINES #####
class EngineError(CoreError):
    """An engine refused a request before touching any resource."""


class DispatchError(EngineError):
    """The dispatch engine refused a work or a schedule."""


class ScheduleError(DispatchError, ValueError):
    """A schedule whose cron is no cron expression."""


class UnknownWorkError(DispatchError, LookupError):
    """A schedule naming a kind no work is registered for."""


##### PROCESSORS #####
class ProcessorError(CoreError):
    """A processor refused its input."""


class MDError(ProcessorError, RuntimeError):
    """The processor refused the input before any conversion: not a format it knows, or too big."""


class UnsupportedFormatError(MDError):
    """No format was detected from the bytes and name: outside the spectrum, so it is not guessed."""


class InputTooLargeError(MDError):
    """The file crosses MD_MAX_INPUT_BYTES: rejected before the engine is invoked."""


class ZipBombError(MDError):
    """The archive crosses MD_ZIP_MAX_ENTRIES or MD_ZIP_MAX_BYTES: its members are never read."""


##### OPS #####
class OpsError(CoreError):
    """An agnostic tool refused its input."""


class ComposeError(OpsError, ValueError):
    """A fragment, a selection or a policy the compose engine refuses to interpret."""


class RegistryError(OpsError, ValueError):
    """An empty scope, a syntax the parser refuses, or a discover target the registry will not interpret."""


class FileError(OpsError, TypeError):
    """A discover target the file tool refuses to interpret."""


class LogoError(OpsError, ValueError):
    """A name, prefix or color the generator refuses to render."""


class CryptoError(OpsError):
    """The crypto engine refused: key material missing, corrupt input or failed decryption."""


class TokenFailure(StrEnum):
    """Distinct reasons a JWT token will not pass validation."""

    MALFORMED = "malformed"  # count "." ≠ JWS(2) / JWE(4)
    EXPIRED = "expired"  # exp claim validation failed
    FORGED = "forged"  # signature mismatch with our keys
    INVALID_CLAIM = "invalid_claim"  # issuer/audience mismatch
    EMPTY_JWE = "empty_jwe"  # decrypted payload was None
    MISSING_FIELD = "missing_field"  # required claim absent


class TokenError(CryptoError):
    """A token that will not pass: malformed, forged, expired or failing its claim registry."""

    def __init__(self, message: str, *, kind: TokenFailure = TokenFailure.MALFORMED) -> None:
        super().__init__(message)
        self.kind = kind
