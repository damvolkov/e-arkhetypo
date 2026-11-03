"""infra/auth/models: who may call, and with what — the vocabulary every auth engine and its doors speak.

A caller is an account and its role, or nobody (anonymous). An account is a person or the admin, its id the keyed
digest of the name it was made with. A grant is one credential of an account, kept by its digest only: a `key` today
(handed out once, revoked by a call, expiring only if configured), `refresh` and `access` reserved for an OAuth2
engine over the same records. What a route or a tool demands is its access, ranked against the caller's role."""

from datetime import datetime
from enum import StrEnum, auto
from typing import Final

import msgspec


class Role(StrEnum):
    """What a caller is: the admin, an account of a person, or nobody."""

    ADMIN = auto()
    USER = auto()
    ANONYMOUS = auto()


class Access(StrEnum):
    """What an entry demands: nothing read (public), any caller (anonymous), an account (user), the admin."""

    PUBLIC = auto()
    ANONYMOUS = auto()
    USER = auto()
    ADMIN = auto()


class GrantKind(StrEnum):
    """A credential's kind: a long-lived key; an OAuth2 engine's refresh and access tokens."""

    KEY = auto()
    REFRESH = auto()
    ACCESS = auto()


class Caller(msgspec.Struct, frozen=True, kw_only=True):
    """Who is asking: an account's id, name and role, or nobody."""

    owner: str = ""
    name: str = ""
    role: Role = Role.ANONYMOUS


class Account(msgspec.Struct, frozen=True, kw_only=True):
    """A person or the admin: the keyed digest of its name, the name, its role, since when."""

    owner: str
    name: str
    role: Role
    created: datetime | None = None


class Grant(msgspec.Struct, frozen=True, kw_only=True):
    """One credential of an account, by its digest: its kind, when it was issued, when it expires and was revoked."""

    digest: str
    owner: str
    kind: GrantKind = GrantKind.KEY
    created: datetime | None = None
    expires: datetime | None = None
    revoked: datetime | None = None


class Issued(msgspec.Struct, frozen=True, kw_only=True):
    """An account and a fresh credential of it, shown this once."""

    owner: str
    name: str
    role: Role
    token: str
    expires: datetime | None = None


### nobody: the shared surface only.
ANONYMOUS: Final[Caller] = Caller()
