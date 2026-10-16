"""ops.stack: read stack/ into the flat service map — every compose as a node, its sidecar files, and the dependency edges resolved from host references.

Discovery walks ``stack/<category>/<service>/`` (underscore or dotted names are scaffolding, skipped); each service
owns a ``compose.yml`` plus any associated config, entrypoint or provisioning file. Dependencies are not declared
(there is no ``depends_on``): they are *named* — one service reaches another by its Docker hostname inside a URL, an
env value or a sidecar config. So the whole tree is read as text and every ``scheme://host`` token that matches a
known service name becomes an edge. The transitive machinery is shared with the module graph via ``ops.deps``.
"""

import re
from typing import TYPE_CHECKING

from e_management.models.stack import SCHEMA, Service, Stack
from e_management.ops.deps import closure, digest, levels, reverse

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

HOST: re.Pattern[str] = re.compile(r"://([a-z][a-z0-9._-]*)(?=[/:]|$)", re.MULTILINE)
NON_SERVICE: frozenset[str] = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"})
SERVICE_FILE: str = "compose.yml"


##### DISCOVERY #####
def _dirs(parent: Path) -> Iterator[tuple[str, Path]]:
    return (
        (category.name, service)
        for category in sorted(p for p in parent.iterdir() if p.is_dir())
        if not category.name.startswith((".", "_"))
        for service in sorted(p for p in category.iterdir() if p.is_dir() and (p / SERVICE_FILE).is_file())
        if not service.name.startswith((".", "_"))
    )


def names(parent: Path) -> frozenset[str]:
    """The vocabulary of service names — the hosts a reference may resolve to."""
    return frozenset(directory.name for _, directory in _dirs(parent))


def _port(text: str) -> int | None:
    label = re.search(r'stack\.port:\s*"?(\d+)"?', text)
    return int(label[1]) if label else None


##### REFERENCES #####
def hosts(text: str) -> frozenset[str]:
    """Every service host a piece of text names: a ``scheme://host[:port]`` token, self and loopback excluded."""
    return frozenset(HOST.findall(text)) - NON_SERVICE


def _blobs(service: Path, stack: Path) -> dict[str, bytes]:
    """The repo-relative files of one service — keyed by path so the digest never collapses two compose.yml."""
    return {
        path.relative_to(stack.parent).as_posix(): path.read_bytes()
        for path in sorted(service.rglob("*"))
        if path.is_file()
    }


##### RESOLUTION #####
def resolve(parent: Path) -> Stack:
    """The whole stack map: nodes with their files and port, edges resolved against the service vocabulary, closed and levelled."""
    known = names(parent)
    services = sorted(_dirs(parent), key=lambda pair: (pair[0], pair[1].name))
    blobs = {directory.name: _blobs(directory, parent) for _, directory in services}
    texts = {name: "\n".join(blob.decode(errors="ignore") for blob in files.values()) for name, files in blobs.items()}
    deps = {name: hosts(texts[name]) & known - {name} for name in blobs}
    back = reverse(deps)
    rank = levels(deps)
    sources = {path: blob for files in blobs.values() for path, blob in files.items()}
    return Stack(
        schema=SCHEMA,
        root="stack",
        categories=tuple(sorted({category for category, _ in services})),
        inputs_hash=digest(sources, (f"schema={SCHEMA}", f"known={sorted(known)}")),
        services=tuple(
            Service(
                name=directory.name,
                category=category,
                compose=(directory / SERVICE_FILE).relative_to(parent.parent).as_posix(),
                files=tuple(sorted(path for path in blobs[directory.name] if not path.endswith(SERVICE_FILE))),
                port=_port((directory / SERVICE_FILE).read_text()),
                depends=tuple(sorted(deps[directory.name])),
                dependents=tuple(sorted(back[directory.name])),
                closure=tuple(sorted(closure(deps[directory.name], deps))),
                level=rank[directory.name],
            )
            for category, directory in services
        ),
    )
