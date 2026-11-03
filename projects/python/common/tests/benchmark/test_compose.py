"""tests/benchmark/test_compose: four times the fragments must not cost four orders — the merge is linear by construction and this test keeps it that way."""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from e_infra.ops.compose import StackCompose


async def test_compose_merge_is_linear(tool: StackCompose, small_docs: list[dict], large_docs: list[dict]) -> None:
    small = time.perf_counter()
    tool.merge(documents=small_docs)
    small_time = time.perf_counter() - small
    large = time.perf_counter()
    merged = tool.merge(documents=large_docs)
    large_time = time.perf_counter() - large
    assert len(merged.services) == 4000
    assert large_time < 0.25
    assert small_time < large_time < small_time * 12
