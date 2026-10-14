"""runners.agnostic.standard/checksum: an identifier's check digit holds — ISIN, CUSIP, LEI.

The digit each standard appends is recomputed from the body and compared: ISO 6166 for ISINs (letters
expanded to digits, Luhn over the eleven leading characters), the CUSIP weighting (even positions
doubled, every product digit-summed), and ISO 17442 for LEIs (ISO 7064 MOD 97-10 over the whole expanded
string: the remainder must be 1). A malformed value does not raise: it is simply a checksum that does
not hold — the audit's verdict, not the runner's crash."""

from collections.abc import Callable, Mapping
from enum import StrEnum, auto
from types import MappingProxyType
from typing import Annotated, Any, Final

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import WORDS, Call

VALUE: Final[str] = rf"^[a-z]+/[A-Z]{{3}}-{WORDS}\.[a-z][a-z0-9_]*$"
LETTERS: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MODULUS: Final[int] = 97


class Scheme(StrEnum):
    """The standard that defines the check digit."""

    ISIN = auto()
    CUSIP = auto()
    LEI = auto()


LENGTHS: Final[Mapping[Scheme, int]] = MappingProxyType({Scheme.ISIN: 12, Scheme.CUSIP: 9, Scheme.LEI: 20})


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`scheme`: the standard, `isin` · `cusip` · `lei`; `value`: where the identifier lives,
    `<section>/<spec>.<field>` — an address in the run's context and the field holding the string."""

    scheme: Scheme
    value: Annotated[str, msgspec.Meta(pattern=VALUE)]

    @staticmethod
    def expand(value: str) -> str:
        """Letters to digits the standards agree on: A is 10 through Z is 35, digits keep their face."""
        return "".join(str(LETTERS.index(char) + 10) if char in LETTERS else char for char in value)

    @staticmethod
    def luhn_digit(body: str) -> int:
        """The Luhn check digit that closes an expanded body: positions 1, 3, 5... doubled, products digit-summed."""
        total = sum(
            (doubled := digit * 2) // 10 + doubled % 10 if position % 2 else digit
            for position, digit in enumerate([int(char) for char in reversed(body)], start=1)
        )
        return (10 - total % 10) % 10

    @classmethod
    def luhn_check(cls, body: str, digit: str) -> bool:
        """Whether the printed digit is the one that closes the body."""
        return cls.luhn_digit(body) == int(digit)

    @classmethod
    def isin(cls, value: str) -> bool:
        """ISO 6166: two letters, nine alphanumeric, a Luhn check digit closing the eleven expanded."""
        match value:
            case str() if len(value) == LENGTHS[Scheme.ISIN] and value[:2].isalpha() and value[2:11].isalnum():
                return cls.luhn_check(cls.expand(value[:11]), value[11])
            case _:
                return False

    @classmethod
    def cusip(cls, value: str) -> bool:
        """CUSIP: eight characters and a check — even positions doubled, every product digit-summed."""
        match value:
            case str() if len(value) == LENGTHS[Scheme.CUSIP] and value.isalnum() and value[8].isdigit():
                total = sum(
                    sum(divmod(cls._value_of(char) * (2 - position % 2), 10))
                    for position, char in enumerate(value[:8], start=1)
                )
                return (10 - total % 10) % 10 == int(value[8])
            case _:
                return False

    @classmethod
    def lei(cls, value: str) -> bool:
        """ISO 17442: twenty characters; ISO 7064 MOD 97-10 over the expanded string leaves a remainder of 1."""
        match value:
            case str() if len(value) == LENGTHS[Scheme.LEI] and value.isalnum() and value.isupper():
                return int(cls.expand(value)) % MODULUS == 1
            case _:
                return False

    @staticmethod
    def _value_of(char: str) -> int:
        """The CUSIP value of one character: digit face, letter 10 to 35."""
        return LETTERS.index(char) + 10 if char in LETTERS else int(char)

    @property
    def holds(self) -> Callable[[str], bool]:
        """The scheme's own verifier."""
        return CHECKS[self.scheme]


CHECKS: Final[Mapping[Scheme, Callable[[str], bool]]] = MappingProxyType(
    {Scheme.ISIN: Args.isin, Scheme.CUSIP: Args.cusip, Scheme.LEI: Args.lei}
)


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The identifier as read, and whether its check digit holds under the named standard."""
    address, _, field = call.args.value.rpartition(".")
    section, _, spec = address.partition("/")
    value = getattr(state.context, section)[spec][field]
    return {"value": value, "holds": call.args.holds(value)}
