"""tests/benchmark/conftest: the services behind the live app, faked (`support.app`), as every tier runs them."""

from support.app import keys, psqlpy, redis_server

__all__ = ["keys", "psqlpy", "redis_server"]
