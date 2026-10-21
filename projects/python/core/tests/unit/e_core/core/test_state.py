"""tests/unit: the resource graph — deep dynamic shape, named navigation, subtree seal."""

import pytest

from e_core.core.state import State


def test_deep_dynamic_assignment_from_zero() -> None:
    state = State()
    state.buses.events.sinks = []
    state.buses.events.sinks.append("stdout")
    assert state.buses["events"].sinks == ["stdout"]
    assert sorted(state.buses) == ["events"]


def test_open_reads_auto_vivify_and_stay_identity_stable() -> None:
    state = State()
    assert state.adapters is state.adapters  # created on first touch, same child ever after


def test_navigation_is_attribute_first() -> None:
    crypto = object()
    state = State(adapters=State(sqlite=object()), crypto=crypto)
    assert state.crypto is crypto
    assert state["crypto"] is crypto
    assert "sqlite" in state.adapters
    assert sorted(state) == ["adapters", "crypto"]
    assert len(state) == 2


def test_seal_freezes_the_whole_subtree() -> None:
    state = State()
    state.adapters.sqlite = object()
    state.crypto = object()
    state.seal()
    with pytest.raises(RuntimeError, match="Sealed"):
        state.extra = 1
    with pytest.raises(RuntimeError, match="Sealed"):
        state.adapters.redis = object()
    with pytest.raises(AttributeError, match="crypto"):
        _ = state.nope  # after seal a typo raises; it does not silently create a node


def test_is_a_mapping_for_the_host_framework() -> None:
    state = State()
    state.a.b = 1
    assert dict(state.a) == {"b": 1}
    snapshot = state.copy()
    assert snapshot.a["b"] == 1
    assert snapshot["a"] is state["a"]


def test_item_surface_and_repr_while_open() -> None:
    state = State()
    state["crypto"] = object()
    assert "crypto" in state
    assert state.crypto is state["crypto"]
    assert state.setdefault("quota", 7) == 7
    assert repr(state) == "State(crypto, quota)"
    del state["crypto"]
    del state.quota
    assert list(state) == []


def test_seal_freezes_the_item_surface_too() -> None:
    state = State()
    state.a = 1
    state.seal()
    with pytest.raises(RuntimeError, match="Sealed"):
        state["b"] = 2
    with pytest.raises(RuntimeError, match="Sealed"):
        del state["a"]


def test_private_lookups_never_vivify() -> None:
    state = State()
    with pytest.raises(AttributeError, match="_skeleton"):
        _ = state._skeleton
