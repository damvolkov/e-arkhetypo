"""ops/hash: hashing without a key — every id a project mints is a hash of what it names.

`hash_text` names a thing by its parts (sha256 over the parts joined by NUL, cut to 16 hex chars), so an unchanged
thing keeps its id; `hash_bytes` is the full sha256 of raw bytes, what tells an unchanged payload from an edited one
(and how a token is stored); `hash_version` is a semver plus a short digest of the config it runs with. Anything that
needs a key or entropy is `ops/crypto`'s."""

import hashlib
from typing import Final

##### HASH #####
### 16 hex chars = 64 bits: collision-free for any catalog a service holds, short enough to print and type.
WIDTH: Final[int] = 16
SEPARATOR: Final[str] = "\0"


def hash_text(*parts: str) -> str:
    """The id of a thing named by its parts: sha256 over the parts joined by NUL, cut to 16 hex chars."""
    return hashlib.sha256(SEPARATOR.join(parts).encode()).hexdigest()[:WIDTH]


def hash_bytes(data: bytes) -> str:
    """The full sha256 of raw bytes: what tells an unchanged payload from an edited one."""
    return hashlib.sha256(data).hexdigest()


def hash_version(semver: str, *config: str) -> str:
    """A versioned thing's version: its semver, then a short digest of the config it runs with — another model or
    config is another version, so what it produced before reads stale."""
    return f"{semver}+{hash_text(*config)[: WIDTH // 2]}"
