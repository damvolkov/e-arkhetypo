"""tests/unit: infra/struct — one validation path, msgspec's, for decoded and constructed models alike."""

from datetime import timedelta
from typing import TYPE_CHECKING, Annotated, Any

import msgspec
import pytest

from e_infra.infra.struct import TRUSTED, CheckedStruct

if TYPE_CHECKING:
    from collections.abc import Callable


class Slug(str):
    """A checked type: a lowercase, hyphenated word list — validated by being built."""

    __slots__ = ()

    def __new__(cls, value: str) -> Slug:
        match value.replace("-", "").isalnum() and value == value.lower() and "--" not in value:
            case True:
                return super().__new__(cls, value)
            case _:
                msg = f"{value!r} is no slug"
                raise ValueError(msg)


class Weights(dict[str, float]):
    """A checked type with derived state: weights that sum to one, their count kept."""

    __slots__ = ("size",)

    def __init__(self, value: Any = (), /) -> None:
        super().__init__(value)
        match abs(sum(self.values()) - 1.0) < 1e-9:
            case True:
                self.size = len(self)
            case _:
                msg = "weights must sum to 1"
                raise ValueError(msg)


class Plan(CheckedStruct, frozen=True, kw_only=True, tag_field="kind", tag="plan"):
    name: Slug
    weights: Weights
    steps: tuple[Slug, ...] = ()
    after: Slug | None = None
    retries: Annotated[int, msgspec.Meta(ge=0)] = 0
    timeout: timedelta | None = None

    def _check(self) -> None:
        match self.after in self.steps:
            case True:
                msg = "after cannot also be a step"
                raise ValueError(msg)
            case _:
                pass


RAW: dict[str, Any] = {"kind": "plan", "name": "daily-run", "weights": {"a": 0.5, "b": 0.5}, "steps": ["fetch"]}


def decode(raw: dict[str, Any]) -> Plan:
    return CheckedStruct.convert(raw, Plan)


def construct(raw: dict[str, Any]) -> Plan:
    """Built in code from plain values: no checked type is ever constructed on the way in."""
    return Plan(**{key: value for key, value in raw.items() if key != "kind"})


BIRTHS: dict[str, Callable[[dict[str, Any]], Plan]] = {"decoded": decode, "constructed": construct}


def test_decoded_into_checked_types() -> None:
    plan = decode({**RAW, "timeout": "PT5S"})
    assert (type(plan.name), type(plan.weights), plan.weights.size, plan.timeout) == (
        Slug,
        Weights,
        2,
        timedelta(seconds=5),
    )


def test_constructed_in_code_is_checked_too() -> None:
    plan = Plan(name=Slug("daily-run"), weights=Weights({"a": 1.0}), steps=(Slug("fetch"),))
    assert plan.steps == ("fetch",)


def test_constructed_from_plain_values_holds_checked_ones() -> None:
    plan = construct({**RAW, "timeout": "PT5S"})
    assert plan == decode({**RAW, "timeout": "PT5S"})
    assert (type(plan.name), type(plan.weights), plan.weights.size, type(plan.steps[0])) == (Slug, Weights, 2, Slug)
    assert plan.timeout == timedelta(seconds=5)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"name": "Daily Run"}, "'Daily Run' is no slug - at `$.name`"),
        ({"steps": ["ok", "Not-OK"]}, "is no slug - at `$.steps[1]`"),
        ({"weights": {"a": 0.4}}, "weights must sum to 1 - at `$.weights`"),
        ({"retries": -1}, "Expected `int` >= 0 - at `$.retries`"),
        ({"after": "fetch"}, "after cannot also be a step"),
    ],
)
@pytest.mark.parametrize("born", list(BIRTHS))
def test_one_path_rejects_both_births(change: dict[str, Any], error: str, born: str) -> None:
    birth = BIRTHS[born]
    with pytest.raises(msgspec.ValidationError) as caught:
        birth({**RAW, **change})
    assert error in str(caught.value)


def test_cross_field_rule_runs_once_per_birth(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    check = Plan._check
    monkeypatch.setattr(Plan, "_check", lambda self: (calls.append(self.name), check(self))[1])
    decode(RAW)
    construct(RAW)
    ### constructed: the original skips `_check`, its round-tripped twin runs it — once per birth either way.
    assert calls == ["daily-run", "daily-run"]


def test_trust_is_scoped_to_the_block() -> None:
    with CheckedStruct.trusted():
        assert TRUSTED.get() is True
    assert TRUSTED.get() is False


def test_hooks_refuse_what_is_no_checked_type() -> None:
    class Opaque:
        pass

    class Holder(CheckedStruct, frozen=True):
        value: Opaque

    with pytest.raises(msgspec.ValidationError, match="is no checked type"):
        msgspec.convert({"value": 1}, Holder, dec_hook=CheckedStruct.dec_hook)
    with pytest.raises(TypeError, match="is no checked type"):
        CheckedStruct.enc_hook(Opaque())


def test_a_checked_type_encodes_as_its_builtin() -> None:
    encoded = msgspec.json.encode(decode(RAW), enc_hook=CheckedStruct.enc_hook)
    assert msgspec.json.decode(encoded) == {**RAW, "after": None, "retries": 0, "timeout": None}
