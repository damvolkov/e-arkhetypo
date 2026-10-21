"""tests/unit: sample fixtures via the pytest-resources plugin (typed load, attr/dict/iter, cache)."""

import pytest
from pytest_resources import FileType, Resources

##### STRUCTURED #####


async def test_resources_loads_json_as_native_dict(resources: Resources) -> None:
    sample = resources.structured.sample
    assert isinstance(sample, dict)
    assert sample["id"] == "sample1"
    assert sample["meta"]["score"] == 0.42


async def test_resources_directory_iterates_parsed_values(resources: Resources) -> None:
    samples = list(resources.structured)
    assert [value["id"] for value in samples] == ["sample1", "sample2"]


async def test_resources_supports_item_access(resources: Resources) -> None:
    assert resources["structured"]["sample2"]["id"] == "sample2"


async def test_resources_navigates_nested_directories(resources: Resources) -> None:
    assert resources.structured.nested.deep["id"] == "deep"


async def test_resources_lists_entry_names(resources: Resources) -> None:
    assert set(resources.structured.keys()) == {"sample", "sample2", "nested"}


##### LOADING RULES #####


async def test_resources_decodes_text_without_parsing_structure(resources: Resources) -> None:
    body = resources.unstructured.sample
    assert isinstance(body, str)
    assert body.startswith("# Sample")


async def test_resources_unregistered_kind_yields_bytes(resources: Resources) -> None:
    assert isinstance(resources.binary.blob, bytes)


async def test_resources_config_formats_route_through_eserde(resources: Resources) -> None:
    assert resources.config.settings["owner"]["name"] == "damien"
    assert resources.config.app["server"] == {"host": "localhost", "port": "8080"}
    assert resources.config.manifest == {"ok": True, "retries": 3}
    assert len(list(resources.config)) == 3


async def test_resources_missing_entry_raises(resources: Resources) -> None:
    with pytest.raises(AttributeError):
        _ = resources.structured.nonexistent


##### LAZY CACHE #####


async def test_resources_caches_parsed_value_at_module_level(resources: Resources) -> None:
    first = resources.structured.sample
    second = resources.structured.sample
    assert first is second


async def test_resources_is_the_same_tree_across_lookups(resources: Resources) -> None:
    assert resources.path.name == "resources"
    assert FileType.of(".json") is FileType.JSON
    assert FileType.of(".nope") is FileType.BINARY
