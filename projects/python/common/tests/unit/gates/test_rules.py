"""The project against its own gates: the commit hook runs `check`, this runs all three phases in the unit suite, so CI
holds the house laws wherever the workflow is assembled."""

from pathlib import Path
from typing import Final

from gates.engine import gate_check, gate_semantic, gate_test

ROOT: Final = Path(__file__).resolve().parents[3]


async def test_rules_hold_over_the_project() -> None:
    assert [str(violation) for violation in (*gate_test(ROOT), *gate_check(ROOT), *gate_semantic(ROOT))] == []
