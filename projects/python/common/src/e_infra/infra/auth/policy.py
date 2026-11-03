"""infra/auth/policy: what a caller may do — pure rules, no store, no door.

`allow` ranks a caller's role against an entry's access: the admin passes everything, an account everything short of
the admin's, nobody only what any caller may. `admit` is the same rule as a verdict: the caller let through, or the
refusal it earns — nobody short of an entry is asked for a key, an account short of it is forbidden —, one typed error
and one message, whichever door maps it. `owns` says whether a caller may act on what someone holds: the admin on
anything, an account on its own, nobody on nothing."""

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from e_infra.infra.auth.models import Access, Role
from e_infra.infra.errors import AnonymousError, ForbiddenError
from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_infra.infra.auth.models import Caller

##### RANKS #####
HELD: Final[Mapping[Role, int]] = MappingProxyType({Role.ANONYMOUS: 0, Role.USER: 1, Role.ADMIN: 2})
DEMANDED: Final[Mapping[Access, int]] = MappingProxyType(
    {Access.PUBLIC: 0, Access.ANONYMOUS: 0, Access.USER: 1, Access.ADMIN: 2}
)


class AuthPolicy:
    """What a caller may do: an access its role reaches, a thing it holds."""

    __slots__ = ()

    ##### PUBLIC #####

    @staticmethod
    def allow(caller: Caller, access: Access) -> bool:
        """Whether the caller's role reaches what the entry demands."""
        return HELD[caller.role] >= DEMANDED[access]

    @staticmethod
    def owns(caller: Caller, holder: str) -> bool:
        """Whether the caller may act on what `holder` holds: the admin always, an account on its own."""
        return caller.role is Role.ADMIN or (bool(caller.owner) and caller.owner == holder)

    @classmethod
    def admit(cls, caller: Caller, access: Access) -> Caller:
        """The caller, when its role reaches what the entry demands — or the refusal it earns."""
        match (cls.allow(caller, access), caller.role):
            case (True, _):
                return caller
            case (False, Role.ANONYMOUS):
                logger.debug("auth policy refused", access=access.value, role=caller.role.value)
                message = f"{access} access: send a key (Authorization: Bearer)"
                raise AnonymousError(message)
            case _:
                logger.debug("auth policy refused", access=access.value, role=caller.role.value, name=caller.name)
                message = f"{access} access: this key's account is {caller.role}"
                raise ForbiddenError(message)
