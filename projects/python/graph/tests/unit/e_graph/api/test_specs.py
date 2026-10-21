"""tests/unit: api.router.specs — the spec-node level, addressed by pipeline and section, as any client would."""

from typing import TYPE_CHECKING

import pytest

from e_graph.logic.errors import CatalogError, Rule, RuleError
from e_graph.logic.orchestrator.lab import SectionLab

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_list_names_every_mounted_section(client) -> None:
    response = client.get("/api/specs/list")
    assert response.status_code == 200
    sections = {(found["pipeline"], found["section"]): found for found in response.json()}
    assert len(sections) == 16
    assert (
        sections["note", "extract"]["specs"],
        sections["note", "extract"]["steps"],
        sections["note", "extract"]["calls"],
    ) == (22, 3, 5)
    assert (sections["filing", "extract"]["specs"], sections["filing", "extract"]["calls"]) == (3, 1)


def test_topology_places_the_section_as_it_runs(client) -> None:
    response = client.get("/api/specs/topology/filing/extract")
    assert response.status_code == 200
    mapped = response.json()
    assert [node["id"] for node in mapped["nodes"]] == ["EXT-balance", "EXT-cover", "EXT-income"]
    assert mapped["calls"][0]["specs"] == ["EXT-balance", "EXT-cover", "EXT-income"]
    assert mapped["nodes"][2]["runners"] == {
        "pre": "agnostic/document/pages",
        "post": "agnostic/number/scale",
        "check": "agnostic/context/present",
    }


def test_svg_draws_the_section(client) -> None:
    response = client.get("/api/specs/svg/doc/extract")
    assert (response.status_code, response.headers["content-type"]) == (200, "image/svg+xml")
    assert "EXT&#45;amount" in response.text


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("/api/specs/topology/nope/extract", "no pipeline 'nope'"),
        ("/api/specs/topology/filing/validate", "filing mounts no 'validate'"),
        ("/api/specs/svg/doc/audit", "doc mounts no 'audit'"),
    ],
)
def test_an_unknown_pipeline_or_section_is_a_404(client, path: str, detail: str) -> None:
    response = client.get(path)
    assert (response.status_code, detail in response.json()["detail"]) == (404, True)


def test_simulate_rehearses_up_to_the_section(client) -> None:
    response = client.post("/api/specs/simulate/doc/transform", json={"data": {"document": "invoice 1 total 4.20"}})
    assert response.status_code == 200
    simulation = response.json()
    assert [run["section"] for run in simulation["runs"]][-2:] == ["validate", "transform"]
    assert simulation["written"] == {
        "TRF-record": {"kind": "invoice", "digest": simulation["written"]["TRF-record"]["digest"], "amount": "4.20"}
    }
    assert simulation["live"] is False


def test_a_section_breaking_its_laws_is_a_422_naming_every_breach(client, mocker: MockerFixture) -> None:
    breach = RuleError(Rule.ORPHAN, "owned/retired", "deprecated runner")
    mocker.patch.object(SectionLab, "map", side_effect=CatalogError("doc/extract: 1 broken laws", [breach]))
    mocker.patch.object(SectionLab, "simulate", side_effect=CatalogError("doc/extract: 1 broken laws", [breach]))
    for response in (
        client.get("/api/specs/topology/doc/extract"),
        client.post("/api/specs/simulate/doc/extract", json={}),
    ):
        assert response.status_code == 422
        assert response.json()["extra"]["breaches"] == ["[orphan] owned/retired: deprecated runner"]
