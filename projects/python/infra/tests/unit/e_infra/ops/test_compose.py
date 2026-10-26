"""tests/unit/e_infra/ops/test_compose: discover, merge, policy — every rule the tool claims has a golden snapshot pinning its output model."""

from typing import TYPE_CHECKING

import eserde
import msgspec
import pytest

from e_infra.ops.compose import ComposeError, SpecCompose, StackCompose

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

##### DISCOVER #####


@pytest.mark.parametrize("with_deps", [False, True], ids=["flat", "deps"])
async def test_discover_catalogs_tree(tool: StackCompose, snap: Callable[[str, bytes], None], with_deps: bool) -> None:
    """The catalog of the resource tree: four services, categories from the parent dir, ports from the labels."""
    catalog = tool.discover(dependencies=with_deps)
    snap("catalog_deps" if with_deps else "catalog", eserde.dumps(msgspec.to_builtins(list(catalog)), format="json"))
    assert [e.name for e in catalog] == ["redis", "openwebui", "vllm", "postgres"]
    assert {(e.category, e.port) for e in catalog} == {("front", 8080), ("rdb", 5432), ("cdb", 6379), ("llm", 8000)}
    assert all(e.path.endswith("compose.yml") for e in catalog)


async def test_discover_names_dependencies(tool: StackCompose) -> None:
    """openwebui reaches vllm by hostname in its env: the edge appears when asked for, and only when asked for."""
    assert all(e.depends == () for e in tool.discover())
    named = {e.name: e.depends for e in tool.discover(dependencies=True)}
    assert "vllm" in named["openwebui"]
    assert named["vllm"] == ()


##### MERGE #####


async def test_merge_tree_imposes_identity_and_volumes(tool: StackCompose, snap: Callable[[str, bytes], None]) -> None:
    """Chosen names merge from the tree; the imposable laws always apply: identity and ./data/<service>/ volumes."""
    merged = tool.merge(["openwebui", "postgres", "redis"])
    snap("merge_tree", merged.snapshot())
    doc = merged.document()
    assert all((s["container_name"], s["hostname"]) == (n, n) for n, s in doc["services"].items())
    assert "./data/postgres/postgres-data:/var/lib/postgresql/data" in doc["services"]["postgres"]["volumes"]
    assert (
        "./data/openwebui/static/favicon.svg:/app/build/static/favicon.svg:ro"
        in doc["services"]["openwebui"]["volumes"]
    )
    assert "volumes" not in doc


async def test_merge_expands_includes_the_way_compose_does(tmp_path: Path) -> None:
    """``include:`` in a tree service splices the fragment in — fragments first, the including body after."""
    service = tmp_path / "llm" / "bridge"
    service.mkdir(parents=True)
    (service / "sidecar.yml").write_text("services:\n  proxy:\n    image: envoy\n")
    (service / "compose.yml").write_text("include:\n  - sidecar.yml\nservices:\n  bridge:\n    image: env\n")
    merged = StackCompose(tmp_path).merge()
    assert set(merged.services) == {"bridge", "proxy"}


async def test_merge_documents_unions_and_collides(
    fragments: dict[str, dict], snap: Callable[[str, bytes], None]
) -> None:
    """In-memory fragments: disjoint names union, collisions follow compose rules, cross-service references travel intact."""
    merged = StackCompose().merge(
        documents=[
            fragments[k] for k in ("api", "api_override", "db", "cache", "fragments", "ports_variants", "resources")
        ]
    )
    snap("merge_documents", merged.snapshot())
    api = merged.services["api"]
    assert api["image"] == "example/api:2.0"
    assert api["ports"].count("9999:9999/udp") == 1
    assert api["environment"]["LOG"] == "debug"
    assert api["environment"]["DATABASE_URL"] == "postgres://db:5432/app"
    assert api["labels"] == {"tier": "frontend", "owner": "platform"}
    assert merged.services["worker"]["environment"]["API_URL"] == "http://web:80"
    assert "x-common" in merged.extensions


async def test_merge_rejects_unknown_service(tool: StackCompose) -> None:
    with pytest.raises(ComposeError, match="Unknown services"):
        tool.merge(["nosuch"])


async def test_merge_rejects_include(tool: StackCompose) -> None:
    with pytest.raises(ComposeError, match="include"):
        tool.merge(documents=[{"include": ["base.yml"]}])


async def test_merge_without_root_needs_documents() -> None:
    with pytest.raises(ComposeError, match="no root"):
        StackCompose().merge()


##### POLICY #####


async def test_policy_configures_ports_network_and_volumes(
    tool: StackCompose, snap: Callable[[str, bytes], None]
) -> None:
    """The declarable policy over the tree: patterned ports, unified network, custom volume root."""
    policed = tool.configure(ports="127.0.0.1:{host}", network="mynet", volume_root="/srv/data", project="prod")
    merged = policed.merge()
    snap("policy_all", merged.snapshot())
    doc = merged.document()
    assert doc["name"] == "prod"
    assert all(set(s["networks"]) == {"mynet"} for s in doc["services"].values())
    assert doc["networks"] == {"mynet": {"name": "stack"}}
    assert "/srv/data/vllm/vllm-cache" in " ".join(doc["services"]["vllm"]["volumes"])


async def test_policy_ports(fragments: dict[str, dict]) -> None:
    """Interpolated entries pass through; literal ones take the pattern, protocol and ip bindings respected."""
    merged = StackCompose(ports="127.0.0.1:{host}").merge(documents=[fragments["ports_variants"]])
    ports = merged.services["matrix"]["ports"]
    assert "${MATRIX_PORT:-7880}:7880" in ports
    entry = next(p for p in ports if isinstance(p, dict))
    assert entry["host_ip"] == "127.0.0.1"
    assert entry["published"] == "5000"
    assert entry["protocol"] == "udp"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [({"ports": "{nope}"}, "Unknown fields"), ({"ports": "{name}{unknown}"}, "Unknown fields")],
    ids=["unknown-field", "second-unknown"],
)
async def test_spec_rejects_bad_policy(kwargs: dict, reason: str) -> None:
    with pytest.raises(ComposeError, match=reason):
        SpecCompose(**kwargs)


async def test_configure_is_pure(tool: StackCompose) -> None:
    """configure answers a new tool; the original keeps its policy."""
    altered = tool.configure(network="other")
    assert tool.merge(["redis"]).document()["networks"] == {"stack": {"name": "stack"}}
    assert altered.merge(["redis"]).document()["networks"] == {"other": {"name": "stack"}}


##### OUTPUT MODEL #####


async def test_merged_is_deterministic_and_idempotent(tool: StackCompose) -> None:
    """Same tree, same bytes; feeding the rendered document back answers the same model."""
    first = tool.merge()
    assert first.snapshot() == tool.merge().snapshot()
    reloaded = StackCompose().merge(documents=[eserde.loads(tool.dump(first), format="yaml")])
    assert reloaded.snapshot() == first.snapshot()


async def test_full_stack(repo: Path, snap: Callable[[str, bytes], None]) -> None:
    """The whole real stack through the tool: catalog with resolved edges and the merged model, pinned."""
    live = StackCompose(repo / "stack")
    assert len(live.discover(dependencies=True)) == 36
    merged = live.merge()
    snap("full_stack", merged.snapshot())
    assert list(merged.services) == sorted(merged.services)
    assert list(merged.networks) == ["stack"]
