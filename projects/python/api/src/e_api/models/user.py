"""models/user: the User DTO family — msgspec contracts for the API edge.

Write model (`UserCreate`) and read model (`User`) are separate structs by construction: the password
and its hash physically do not exist on `User`, so no serializer can leak them. `UserUpdate` uses the
`UNSET` sentinel to tell "field absent" from "field null".
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import msgspec

##### CONSTANTS #####
REDACTED: str = "**********"
USERNAME_PATTERN: str = r"^[a-z][a-z0-9_]{2,31}$"
EMAIL_PATTERN: str = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
PASSWORD_MIN: int = 12


##### TYPES #####
class Password(str):
    """Password text that never leaks through repr/str/f-strings; the value is still `str(self)`-intact upstream."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"Password('{REDACTED}')"

    __str__ = __repr__


##### DTOs #####
class UserCreate(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Inbound registration payload.

    Meta reaches plain `str` (patterns, lengths); the newtype and the Decimal range are invariants the
    object guards itself — msgspec runs `__post_init__` right after decode, so validation is still at the edge.
    """

    username: Annotated[str, msgspec.Meta(pattern=USERNAME_PATTERN)]
    email: Annotated[str, msgspec.Meta(max_length=254, pattern=EMAIL_PATTERN)]
    password: str
    birth: date | None = None
    quota: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if len(self.password) < PASSWORD_MIN:
            msg = f"password must be at least {PASSWORD_MIN} characters"
            raise ValueError(msg)
        if self.quota < 0:
            msg = "quota cannot be negative"
            raise ValueError(msg)
        ### msgspec decodes plain str (it refuses str->subclass coercion); the object upgrades itself here.
        object.__setattr__(self, "password", Password(self.password))


class User(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """Outbound read model — no credential field exists here."""

    id: UUID
    username: str
    email: str
    birth: date | None = None
    quota: Decimal = Decimal(0)
    created: datetime


class UserUpdate(msgspec.Struct, frozen=True, kw_only=True):
    """Partial mutation: UNSET means "not sent", None means "set to null"."""

    email: msgspec.UnsetType | Annotated[str, msgspec.Meta(max_length=254, pattern=EMAIL_PATTERN)] = msgspec.UNSET
    birth: msgspec.UnsetType | date | None = msgspec.UNSET
    quota: msgspec.UnsetType | Decimal = msgspec.UNSET

    def __post_init__(self) -> None:
        if self.quota is not msgspec.UNSET and self.quota < 0:
            msg = "quota cannot be negative"
            raise ValueError(msg)


class UserRecord(msgspec.Struct, frozen=True, kw_only=True):
    """Storage model — the only type that carries `password_hash`; it never crosses the API boundary."""

    id: UUID
    username: str
    email: str
    password_hash: str
    birth: date | None = None
    quota: Decimal = Decimal(0)
    created: datetime
