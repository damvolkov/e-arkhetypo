"""tests/unit: the DARTS taxonomy on disk — `specs/<pipeline>/` and `runners/<pipeline>/` hold one folder per section."""

from pathlib import Path

import pytest

from e_graph.models.section import ORDER, Section

PACKAGE: Path = Path(__file__).resolve().parents[3] / "src" / "e_graph"


@pytest.mark.parametrize("tree", ["specs", "runners"])
def test_each_pipeline_mirrors_the_sections(tree: str) -> None:
    pipelines = [
        path for path in (PACKAGE / tree).iterdir() if path.is_dir() and path.name not in {"wiki", "__pycache__"}
    ]
    assert pipelines, f"{tree}/ holds one folder per pipeline"
    for pipeline in pipelines:
        folders = {
            path.name for path in pipeline.iterdir() if path.is_dir() and path.name not in {"wiki", "__pycache__"}
        }
        assert folders == set(Section), f"{tree}/{pipeline.name} must mirror Section: {sorted(folders ^ set(Section))}"


def test_sections_keep_their_fixed_order() -> None:
    assert [section.value for section in ORDER][:2] == ["ingest", "normalize"]
    assert ORDER[-1] is Section.REPORT
