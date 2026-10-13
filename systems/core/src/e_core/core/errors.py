"""core/errors: typed exception hierarchy — all domain exceptions inherit from CoreError."""

from enum import StrEnum


##### ROOT #####
class CoreError(Exception):
    """All e-core exceptions inherit from this root."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


##### CRYPTO #####
class CryptoError(CoreError):
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
