"""tests/unit: api.deps — the wiring vocabulary."""

from e_api.api.deps import DepKey


def test_dep_key_values_are_the_link_parameter_names() -> None:
    """StrEnum auto() lowercases the member name: the enum and the injected signature cannot drift apart."""
    assert [key.value for key in DepKey] == ["graph", "store", "auth", "caller", "correlation_id"]
