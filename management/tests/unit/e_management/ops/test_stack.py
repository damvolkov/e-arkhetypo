"""tests/unit/e_management/ops/stack: discovery over a synthetic stack/ — compose services and host-only setup services."""

from typing import TYPE_CHECKING

import pytest

from e_management.ops.stack import resolve

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """stack/ with one compose service, one host-only service and one folder that is neither."""
    stack = tmp_path / "stack"
    (stack / "cdb" / "redis").mkdir(parents=True)
    (stack / "cdb" / "redis" / "compose.yml").write_text('labels:\n  stack.port: "6379"\n')
    (stack / "watch" / "lazydocker").mkdir(parents=True)
    (stack / "watch" / "lazydocker" / "setup.sh").write_text("#!/usr/bin/env bash\n")
    (stack / "watch" / "lazydocker" / "config.yml").write_text("gui: {}\n")
    (stack / "watch" / "empty").mkdir(parents=True)
    return stack


def test_resolve_compose_service(tree: Path) -> None:
    redis = resolve(tree).service("redis")
    assert (redis.compose, redis.port, redis.paths) == (
        "stack/cdb/redis/compose.yml",
        6379,
        ("stack/cdb/redis/compose.yml",),
    )


def test_resolve_setup_service(tree: Path) -> None:
    host = resolve(tree).service("lazydocker")
    assert (host.compose, host.port) == (None, None)
    assert host.paths == ("stack/watch/lazydocker/config.yml", "stack/watch/lazydocker/setup.sh")


def test_resolve_skips_folder_without_entrypoint(tree: Path) -> None:
    assert resolve(tree).names() == ("redis", "lazydocker")
