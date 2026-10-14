"""Pure logic and its value: no server involved."""

import msgspec
import pytest

from e_mcp.logic.echo import greet
from e_mcp.models.echo import Echo


@pytest.mark.parametrize(("name", "expected"), [("world", "hello world"), ("", "hello world"), ("ada", "hello ada")])
def test_echo_greet(name: str, expected: str) -> None:
    assert greet(name) == expected


def test_echo_model() -> None:
    assert msgspec.to_builtins(Echo(message="hi", port=1)) == {"message": "hi", "port": 1}
