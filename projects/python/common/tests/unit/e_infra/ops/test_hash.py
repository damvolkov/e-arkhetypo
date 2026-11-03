"""tests/unit/e_infra/ops/hash: keyless names — pinned digests, parts never blur into each other, a version moves with
its config."""

import pytest

from e_infra.ops.hash import hash_bytes, hash_text, hash_version


@pytest.mark.parametrize(
    ("parts", "expected"),
    [(("a", "b"), "59b271ae1bbcb1d3"), ((), "e3b0c44298fc1c14")],
    ids=["parts", "empty"],
)
async def test_hash_text_pinned(parts: tuple[str, ...], expected: str) -> None:
    assert hash_text(*parts) == expected


async def test_hash_text_parts_never_blur() -> None:
    assert len({hash_text("ab", "c"), hash_text("a", "bc"), hash_text("abc"), hash_text("c", "ab")}) == 4


async def test_hash_bytes_full_sha256() -> None:
    assert hash_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


async def test_hash_version_semver_then_config_digest() -> None:
    assert hash_version("1.0.0", "qwen", "768") == "1.0.0+0af13f81"


@pytest.mark.parametrize(
    ("other", "config"),
    [("1.0.1", ("qwen", "768")), ("1.0.0", ("qwen", "1024")), ("1.0.0", ("768", "qwen"))],
    ids=["semver", "config", "order"],
)
async def test_hash_version_stale_on_change(other: str, config: tuple[str, ...]) -> None:
    assert hash_version(other, *config) != hash_version("1.0.0", "qwen", "768")
