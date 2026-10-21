"""e_core.core.proxy: lazy singletons — nothing built at construction, exactly one build on first access."""

from e_core.core.proxy import LazyProxy


async def test_proxy_defers_the_build() -> None:
    calls: list[int] = []

    def build() -> list[int]:
        calls.append(1)
        return calls

    proxy: LazyProxy[list[int]] = LazyProxy(build)
    assert calls == []  # constructing the proxy at module level runs nothing
    assert proxy.count(7) == 0
    assert calls == [1]  # the build fires exactly on the first attribute access


async def test_proxy_builds_exactly_once() -> None:
    builds: list[int] = []

    def build() -> list[int]:
        builds.append(1)
        return []

    proxy: LazyProxy[list[int]] = LazyProxy(build)
    proxy.append(7)
    proxy.append(8)
    assert builds == [1]  # the build ran once, both touches hit the same instance
    assert proxy.count(8) == 1
