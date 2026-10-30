"""ops/compose: discover a stack tree and merge chosen fragments into one parameterized document.

``StackCompose`` reads ``<root>/<category>/<service>/compose.yml`` and answers two things: a flat
catalog of what is available (``discover``, optionally with the host-reference edges each service
names) and the merged document (``merge``), built from the chosen names or from in-memory fragment
mappings — the objects the stack machinery answers for a chosen service. Everything travels on
plain e-serde mappings: anchors and ``<<`` merge keys are resolved at load, so the engine only ever
sees data. The merge follows compose-go rules — unique lists append and dedup, ``environment`` and
``networks`` unify as maps, mappings merge recursively, scalars take the last word — and then
applies the policy: the declarable one held in ``SpecCompose`` (project name, port pattern, network
name, volume root) and the two imposable laws of the house stack, never configurable: every service
carries ``container_name`` and ``hostname`` equal to its name, and every relative or named volume
binds under ``data/<service>/``. Interpolated published ports (``${WEB_PORT:-8080}``) pass through
untouched — they are already parameterized; validation of the result belongs to
``docker compose config`` at deploy time."""

import re
import string
from typing import TYPE_CHECKING, Any

import eserde
import msgspec
from msgspec import Struct, field

from e_infra.infra.errors import ComposeError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

##### TYPES #####


class SpecCompose(Struct, frozen=True, kw_only=True):
    """The declarable policy: project name, port pattern (``{name}`` ``{port}`` ``{host}``), shared network name, volume root.

    A pattern whose result contains a colon sets the ip (short form) or ``host_ip`` (long form);
    the entry's own binding is kept otherwise. Interpolated entries pass through untouched."""

    project: str | None = None
    ports: str | None = None
    network: str | None = None
    volume_root: str = "./data"

    def __post_init__(self) -> None:
        match self.ports:
            case str() as pattern:
                match sorted({f for _, f, _, _ in string.Formatter().parse(pattern) if f} - PORT_FIELDS):
                    case []:
                        return
                    case fields:
                        msg = f"Unknown fields in port pattern: {fields}"
                        raise ComposeError(msg)


class ServiceCompose(Struct, frozen=True, kw_only=True):
    """One discovered compose of the tree: where it lives, what category it belongs to, its port and the services it names."""

    name: str
    category: str
    path: str
    port: int | None = None
    depends: tuple[str, ...] = ()


class MergedCompose(Struct, frozen=True, kw_only=True):
    """The merged output model: services and shared resources, canonically ordered and ready to render."""

    name: str | None = None
    services: dict[str, Any] = field(default_factory=dict)
    volumes: dict[str, Any] = field(default_factory=dict)
    networks: dict[str, Any] = field(default_factory=dict)
    configs: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def document(self) -> dict[str, Any]:
        """The compose-ready mapping: empty sections and the missing project name dropped, extensions back to ``x-`` keys."""
        base = {k: v for k, v in msgspec.to_builtins(self).items() if v not in (None, {}, [])}
        extensions = base.pop("extensions", {})
        return {**base, **extensions}

    def snapshot(self) -> bytes:
        """Canonical JSON of the model — the golden bytes the tests pin."""
        return eserde.dumps(self.document(), format="json")


##### RULES #####

COMPOSE_FILE: str = "compose.yml"
HOST: re.Pattern[str] = re.compile(r"://([a-z][a-z0-9._-]*)(?=[/:]|$)", re.MULTILINE)
NON_SERVICE: frozenset[str] = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"})
PORT_FIELDS: frozenset[str] = frozenset({"name", "port", "host"})
RESOURCES: tuple[str, ...] = ("volumes", "networks", "configs", "secrets")
UNION_LISTS: frozenset[str] = frozenset(
    {"ports", "expose", "dns", "dns_search", "extra_hosts", "devices", "group_add", "volumes"}
)


class StackCompose:
    """The tool: discover the tree, merge the choice, configure the policy, render the result.

    Dispatch is structural: the compose class of each key — unique list, environment map, network
    map, nested mapping, plain scalar — decides the rule through ``match``, never through branching
    chains. Nothing given is mutated: every fragment is copied into the merged model."""

    __slots__ = ("_root", "_spec")

    def __init__(self, root: Path | None = None, *, spec: SpecCompose | None = None, **fields: Any) -> None:
        self._root = root
        base = spec if spec is not None else SpecCompose()
        self._spec = msgspec.structs.replace(base, **fields) if fields else base

    ##### PRIVATE #####

    def _discover_entries(self) -> list[tuple[str, Path]]:
        match self._root:
            case None:
                msg = "no root given: pass it to the constructor"
                raise ComposeError(msg)
            case dir:
                return [
                    (service.name, service)
                    for category in sorted(p for p in dir.iterdir() if p.is_dir())
                    if not category.name.startswith((".", "_"))
                    for service in sorted(p for p in category.iterdir() if p.is_dir())
                    if (service / COMPOSE_FILE).is_file() and not service.name.startswith((".", "_"))
                ]

    @staticmethod
    def _discover_port(text: str) -> int | None:
        label = re.search(r'stack\.port:\s*"?(\d+)"?', text)
        return int(label[1]) if label else None

    @staticmethod
    def _discover_deps(text: str, known: frozenset[str]) -> tuple[str, ...]:
        bare = re.findall(r"^-\s*([a-z][a-z0-9_-]*)\s*$", text, re.MULTILINE)
        hosts = {*HOST.findall(text), *bare} - NON_SERVICE
        return tuple(sorted(hosts & known))

    def _merge_documents(
        self, chosen: Iterable[str], documents: Iterable[Mapping[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        services: dict[str, Any] = {}
        resources: dict[str, dict[str, Any]] = {section: {} for section in RESOURCES}
        wanted: frozenset[str] | None = frozenset(chosen) if chosen else None
        for frag in documents:
            match frag:
                case {"include": _}:
                    msg = "include is not supported: pass the included fragment in the list instead"
                    raise ComposeError(msg)
            for name, svc in (frag.get("services") or {}).items():
                services[name] = self._merge_service(services[name], svc) if name in services else dict(svc or {})
            for section in RESOURCES:
                for key, val in (frag.get(section) or {}).items():
                    resources[section][key] = {**(resources[section].get(key) or {}), **(val or {})}
        match wanted:
            case None:
                return services, resources
            case names:
                absent = names - frozenset(services)
                match sorted(absent):
                    case []:
                        return {k: v for k, v in services.items() if k in names}, resources
                    case missing:
                        msg = f"Unknown services requested: {missing}"
                        raise ComposeError(msg)

    def _merge_load(self, entries: list[tuple[str, Path]]) -> list[dict[str, Any]]:
        return [document for _, directory in entries for document in self._compose_of(directory / COMPOSE_FILE)]

    def _compose_of(self, path: Path) -> list[dict[str, Any]]:
        """One compose file as documents, with ``include:`` spliced in the way docker compose does it:
        every included fragment first, the including body after — includes nest."""
        document = eserde.load(path, format="yaml")
        match document.get("include"):
            case None:
                return [document]
            case names:
                body = {key: value for key, value in document.items() if key != "include"}
                return [
                    *(part for name in names for part in self._compose_of((path.parent / name).resolve())),
                    *([body] if body else []),
                ]

    def _merge_service(self, base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(base)
        for key, val in over.items():
            self._merge_rule(out, key, val)
        return out

    def _merge_rule(self, out: dict[str, Any], key: str, val: Any) -> None:
        match (key, out.get(key), val):
            case (k, a, b) if k in UNION_LISTS and isinstance(b, list):
                seen = {repr(e) for e in a or ()}
                out[key] = [*(a or []), *[e for e in b if repr(e) not in seen]]
            case ("environment", old, new):
                out[key] = {**self._merge_env(old), **self._merge_env(new)}
            case ("networks", old, new):
                out[key] = {**self._merge_networks(old), **self._merge_networks(new)}
            case (_, dict() as a, dict() as b):
                out[key] = self._merge_mapping(a, b)
            case _:
                out[key] = val

    @classmethod
    def _merge_mapping(cls, a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(a)
        for key, val in b.items():
            match (out.get(key), val):
                case (dict() as u, dict() as w):
                    out[key] = cls._merge_mapping(u, w)
                case _:
                    out[key] = val
        return out

    @staticmethod
    def _merge_env(env: Any) -> dict[str, str]:
        match env:
            case None:
                return {}
            case dict() as mapping:
                return {k: str(v) for k, v in mapping.items()}
            case list() as items:
                return {kv[0]: kv[1] if len(kv) > 1 else "" for kv in (str(e).split("=", 1) for e in items)}
            case other:
                msg = f"Unsupported environment: {other!r}"
                raise ComposeError(msg)

    @staticmethod
    def _merge_networks(nets: Any) -> dict[str, Any]:
        match nets:
            case None:
                return {}
            case list() as items:
                return {str(n): None for n in items}
            case dict() as mapping:
                return dict(mapping)
            case other:
                msg = f"Unsupported networks: {other!r}"
                raise ComposeError(msg)

    def _merge_port(self, name: str, entry: Any, pattern: str) -> Any:
        match entry:
            case str() as text if "${" in text:
                return entry
            case {"published": str() as pub} if "${" in pub:
                return entry
            case {"target": str() as tgt} if "${" in tgt:
                return entry
        ip, published, target = self._merge_port_split(entry)
        value = pattern.format(name=name.upper(), port=target.partition("/")[0], host=published)
        head, sep, tail = value.rpartition(":")
        host_ip, published = (head or ip, tail) if sep else (ip, value)
        match entry:
            case dict() as long:
                return {**long, "published": published, **({"host_ip": host_ip} if host_ip else {})}
            case _:
                return f"{host_ip}:{published}:{target}" if host_ip else f"{published}:{target}"

    @staticmethod
    def _merge_port_split(entry: Any) -> tuple[str, str, str]:
        match entry:
            case dict() as long:
                return str(long.get("host_ip", "")), str(long.get("published", "")), str(long.get("target", ""))
            case _:
                match str(entry).split(":"):
                    case [container]:
                        return "", container, container
                    case [published, target]:
                        return "", published, target
                    case [ip, published, target]:
                        return ip, published, target
                    case parts:
                        msg = f"Unsupported port syntax: {parts}"
                        raise ComposeError(msg)

    def _merge_volume(self, name: str, entry: Any, declared: frozenset[str]) -> Any:
        source, tail = self._merge_volume_split(entry)
        match (entry, source):
            case ({"type": "tmpfs"}, _):
                return entry
            case (_, s) if not s or s.startswith(("/", "~")):
                return entry
            case (_, s) if s.startswith(f"{self._spec.volume_root}/{name}/"):
                return entry
            case (_, s) if s.startswith(("../", "./")):
                return self._merge_volume_join(f"{self._spec.volume_root}/{name}/{s.split('/', 1)[1]}", tail, entry)
            case (_, s) if s in declared:
                return self._merge_volume_join(f"{self._spec.volume_root}/{name}/{s}", tail, entry)
            case _:
                return entry

    @staticmethod
    def _merge_volume_split(entry: Any) -> tuple[str, str]:
        match entry:
            case dict() as long:
                return str(long.get("source", "")), ""
            case _:
                source, _, tail = str(entry).partition(":")
                return source, tail

    @staticmethod
    def _merge_volume_join(source: str, tail: str, entry: Any) -> Any:
        match entry:
            case dict() as long:
                rest = {k: v for k, v in long.items() if k not in ("source", "type", "volume")}
                return {**rest, "type": "bind", "source": source}
            case _:
                return f"{source}:{tail}" if tail else source

    def _merge_policy(self, services: dict[str, Any], resources: dict[str, dict[str, Any]]) -> None:
        declared = frozenset(resources["volumes"])
        for name, svc in services.items():
            svc["container_name"] = svc["hostname"] = name
            match svc:
                case {"environment": dict() | list() | None as env}:
                    svc["environment"] = dict(sorted(self._merge_env(env).items()))
            match (self._spec.ports, svc.get("ports")):
                case str() as pattern, list() as ports:
                    svc["ports"] = [self._merge_port(name, p, pattern) for p in ports]
            match svc.get("volumes"):
                case list() as vols:
                    svc["volumes"] = [self._merge_volume(name, v, declared) for v in vols]
            match self._spec.network:
                case str() as net:
                    nets = self._merge_networks(svc.get("networks"))
                    svc["networks"] = {net: next(iter(nets.values()), None) if len(nets) <= 1 else None}
        referenced = {
            v.partition(":")[0] if isinstance(v, str) else str(v.get("source", ""))
            for svc in services.values()
            for v in svc.get("volumes") or ()
        }
        resources["volumes"] = {k: v for k, v in resources["volumes"].items() if k in referenced}
        match self._spec.network:
            case str() as net:
                keep = {**(next(iter(resources["networks"].values()), None) or {})}
                resources["networks"] = {net: keep or None}

    ############################################################

    ##### PUBLIC #####

    def configure(self, **fields: Any) -> StackCompose:
        """A new tool with the policy fields replaced — the original stays untouched."""
        return StackCompose(self._root, spec=msgspec.structs.replace(self._spec, **fields))

    def discover(self, *, dependencies: bool = False) -> tuple[ServiceCompose, ...]:
        """The flat catalog of the tree: every service with its category, port and — when asked — the peers it names."""
        entries = self._discover_entries()
        known = frozenset(name for name, _ in entries)
        bodies = {name: (directory / COMPOSE_FILE).read_text() for name, directory in entries}
        return tuple(
            ServiceCompose(
                name=name,
                category=directory.parent.name,
                path=str((directory / COMPOSE_FILE).relative_to(directory.parent.parent)),
                port=self._discover_port(bodies[name]),
                depends=self._discover_deps(bodies[name], known) if dependencies else (),
            )
            for name, directory in entries
        )

    def merge(
        self, chosen: Iterable[str] | None = None, *, documents: Iterable[Mapping[str, Any]] | None = None
    ) -> MergedCompose:
        """One model from the tree (all, or the chosen names) or from in-memory fragments — policy and imposable laws applied."""
        fragments = list(documents) if documents is not None else self._merge_load(self._discover_entries())
        services, resources = self._merge_documents(chosen or (), fragments)
        project = self._spec.project or next((name for frag in fragments if (name := frag.get("name"))), None)
        extensions = {k: v for frag in fragments for k, v in frag.items() if k.startswith("x-")}
        self._merge_policy(services, resources)
        return MergedCompose(
            name=project,
            services=dict(sorted(services.items())),
            **{section: dict(sorted(resources[section].items())) for section in RESOURCES},
            extensions=dict(sorted(extensions.items())),
        )

    def dump(self, merged: MergedCompose) -> bytes:
        """The model rendered as canonical YAML, ready for ``docker compose config``."""
        return eserde.dumps(merged.document(), format="yaml")
