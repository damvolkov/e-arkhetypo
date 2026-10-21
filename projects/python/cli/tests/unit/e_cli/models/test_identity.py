"""tests/unit/e_cli/models/identity: the token travels, it never prints."""

from e_cli.models.identity import Identity, IdentityOrigin


def test_identity_repr_hides_the_token() -> None:
    assert "secret" not in repr(Identity(origin=IdentityOrigin.STORE, token="secret-token-1234"))


def test_identity_masked_keeps_only_the_tail() -> None:
    masked = Identity(origin=IdentityOrigin.STORE, token="secret-token-1234").masked
    assert masked.endswith("1234")
    assert "secret" not in masked
