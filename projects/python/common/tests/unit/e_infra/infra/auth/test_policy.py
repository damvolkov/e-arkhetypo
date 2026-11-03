"""tests/unit/e_infra/infra/auth/policy: a role against an access, the refusal it earns, and who may act on what
someone holds."""

import pytest

from e_infra.infra.auth.models import ANONYMOUS, Access, Caller, Role
from e_infra.infra.auth.policy import AuthPolicy
from e_infra.infra.errors import AnonymousError, ForbiddenError

ANA = Caller(owner="ana", name="ana", role=Role.USER)
ROOT = Caller(owner="root", name="admin", role=Role.ADMIN)


@pytest.mark.parametrize(
    ("caller", "allowed"),
    [
        (ANONYMOUS, [True, True, False, False]),
        (ANA, [True, True, True, False]),
        (ROOT, [True, True, True, True]),
    ],
    ids=["anonymous", "user", "admin"],
)
def test_policy_allow(caller: Caller, allowed: list[bool]) -> None:
    assert [AuthPolicy.allow(caller, access) for access in Access] == allowed


@pytest.mark.parametrize(
    ("caller", "holder", "owns"),
    [(ANA, "ana", True), (ANA, "bob", False), (ANA, "", False), (ROOT, "bob", True), (ANONYMOUS, "", False)],
    ids=["own", "another", "nobody's", "admin", "anonymous"],
)
def test_policy_owns(caller: Caller, holder: str, owns: bool) -> None:
    assert AuthPolicy.owns(caller, holder) is owns


@pytest.mark.parametrize("caller", [ANONYMOUS, ANA, ROOT], ids=["anonymous", "user", "admin"])
def test_policy_admit_lets_who_reaches(caller: Caller) -> None:
    assert AuthPolicy.admit(caller, Access.ANONYMOUS) is caller


def test_policy_admit_anonymous_asks_a_key() -> None:
    with pytest.raises(AnonymousError, match=r"^user access: send a key \(Authorization: Bearer\)$"):
        AuthPolicy.admit(ANONYMOUS, Access.USER)


def test_policy_admit_short_role_is_forbidden() -> None:
    with pytest.raises(ForbiddenError, match=r"^admin access: this key's account is user$"):
        AuthPolicy.admit(ANA, Access.ADMIN)
