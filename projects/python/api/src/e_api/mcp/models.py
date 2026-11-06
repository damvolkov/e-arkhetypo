"""e_api.mcp.models: what an agent sends each tool — one Struct per tool, its fields the tool's arguments.

The registry tells a client their JSON Schema; the answers are the API's own models, save the readiness one. Creating a user takes the API's own
`UserCreate`; reading, updating and deleting one name it by `user_id`, which a route takes from its path."""

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import msgspec

from e_api.engines.health import ProviderHealth
from e_api.models.user import EMAIL_PATTERN


class NoArgs(msgspec.Struct, frozen=True, kw_only=True):
    """A tool that takes nothing."""


class UserArgs(msgspec.Struct, frozen=True, kw_only=True):
    """The user a tool reads or deletes."""

    user_id: UUID


class UserUpdateArgs(msgspec.Struct, frozen=True, kw_only=True):
    """The user to change and what changes: a field left out stays, `null` sets it to null."""

    user_id: UUID
    email: msgspec.UnsetType | Annotated[str, msgspec.Meta(max_length=254, pattern=EMAIL_PATTERN)] = msgspec.UNSET
    birth: msgspec.UnsetType | date | None = msgspec.UNSET
    quota: msgspec.UnsetType | Decimal = msgspec.UNSET


class Status(msgspec.Struct, frozen=True, kw_only=True):
    """Whether the service is ready — every required provider answers — and each provider's verdict."""

    ready: bool
    providers: list[ProviderHealth]
