"""tests/unit: api.deps — the wiring vocabulary and the public read edge over authlib's registry."""

from authlib.integrations.starlette_client import OAuth

from e_api.api.deps import DepKey, registered_providers


def test_dep_key_values_are_the_link_parameter_names() -> None:
    """StrEnum auto() lowercases the member name: the enum and the injected signature cannot drift apart."""
    assert [key.value for key in DepKey] == ["graph", "store", "current_user", "correlation_id", "oauth"]


def test_registered_providers_lists_sorted_names() -> None:
    registry = OAuth()
    registry.register("zeta", client_id="cid", client_secret="sec")
    registry.register("alpha", client_id="cid", client_secret="sec")
    assert registered_providers(registry) == ["alpha", "zeta"]
