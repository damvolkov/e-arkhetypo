"""tests/unit/e_api/api/lifespan/parity: law 22, checked — the attribute chain of the sealed system is the module path.

The real lifespan chain fills and seals the system; the whole tree is walked. Every node whose class is a stratum's
lives in the package its chain names: a `system.logic.store` in `e_api.logic.store`. Tools (ops, adapters, processors,
infra's wrappers, builtins, mappings, third parties) are no node of a stratum; the infrastructure sections (`shared`,
`adapters`) are walked, their own classes never placed. The blueprint mounts no stratum yet: the gate holds for the
first one a project adds. And one object, one path: nothing the system holds lives at two."""


def test_parity_every_node_lives_in_the_package_its_path_names(held: list[tuple[str, str]]) -> None:
    assert [(chain, module) for chain, module in held if not module.startswith(f"e_api.{chain}")] == []


def test_parity_no_object_lives_at_two_paths(twins: list[list[str]]) -> None:
    assert twins == []
