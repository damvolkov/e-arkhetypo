"""tests/benchmark: the merge is a single pass over the fragments — the fixtures build the synthetic load the tests bound."""

from typing import TYPE_CHECKING

import pytest

from e_core.ops.compose import StackCompose

if TYPE_CHECKING:
    from collections.abc import Callable


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything under benchmark/ is a wall-clock probe: marked slow, out of every gate unless asked."""
    for item in items:
        if "benchmark" in item.path.parts:
            item.add_marker(pytest.mark.slow)


@pytest.fixture(scope="session")
def tool() -> StackCompose:
    return StackCompose()


@pytest.fixture(scope="session")
def docs_factory() -> Callable[[int], list[dict]]:
    """Build ``n`` synthetic single-service fragments: disjoint names, one port, two envs, one volume."""

    def _docs(n: int) -> list[dict]:
        return [
            {
                "services": {
                    f"svc{i}": {
                        "image": f"example/x:{i}",
                        "ports": [f"{8000 + i}:80"],
                        "environment": {"A": "1", "B": str(i)},
                    }
                },
                "volumes": {f"v{i}": {}},
            }
            for i in range(n)
        ]

    return _docs


@pytest.fixture(scope="session")
def small_docs(docs_factory: Callable[[int], list[dict]]) -> list[dict]:
    return docs_factory(1000)


@pytest.fixture(scope="session")
def large_docs(docs_factory: Callable[[int], list[dict]]) -> list[dict]:
    return docs_factory(4000)
