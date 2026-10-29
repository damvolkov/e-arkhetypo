"""tests/unit/e_graph/api/lifespan/parity: law 22, checked — the attribute chain of the sealed system is the module path.

The real lifespan chain fills and seals the system; the whole tree is walked. Every node whose class is a stratum's
lives in the package its chain names: `system.logic.orchestrator` under `e_graph.logic.orchestrator`,
`system.instrument.telemetry` in `e_graph.instrument.telemetry`. Tools (ops, adapters, processors, infra's wrappers,
builtins, mappings, third parties) are no node of a stratum; the infrastructure sections (`shared`, `adapters`,
`infra`) are walked, their own classes never placed. And one object, one path: nothing the system holds lives at two."""


def test_parity_every_node_lives_in_the_package_its_path_names(held: list[tuple[str, str]]) -> None:
    ### the agent, the orchestrator, the tracer and the contexts store: every stratum node the app builds is checked.
    assert len(held) >= 4
    assert [(chain, module) for chain, module in held if not module.startswith(f"e_graph.{chain}")] == []


def test_parity_no_object_lives_at_two_paths(twins: list[list[str]]) -> None:
    assert twins == []
