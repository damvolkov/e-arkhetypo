"""infra/auth/models: who may call, and with what — the vocabulary every auth engine and its doors speak.

A caller is an account and its role, or nobody (anonymous). An account is a person or the admin, its id the keyed
digest of the name it was made with, the segments the admin granted it (what of the tenant's it may read beyond the
general: a team, a campaign), and whether it is a delegate — a service the admin trusts to act for the people it
serves (an agent for its customers), naming the subject of each call. A grant is one credential of an account, kept by its digest only: a `key` today
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
    """Who is asking: an account's id, name, role, segments and whether it acts for others, or nobody."""

    owner: str | None = None
    name: str | None = None
    role: Role = Role.ANONYMOUS
    segments: frozenset[str] = frozenset()
    delegate: bool = False


class Account(msgspec.Struct, frozen=True, kw_only=True):
    """A person, a delegate or the admin: the keyed digest of its name, the name, its role, since when, its segments,
    whether it may act for the people it serves."""

    owner: str
    name: str
    role: Role
    created: datetime | None = None
    segments: frozenset[str] = frozenset()
    delegate: bool = False


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
