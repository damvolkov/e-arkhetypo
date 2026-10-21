"""tests/unit: the DARTS taxonomy on disk — the real system passes its own static check, clean, nothing idle."""

from e_graph.logic.discover import SystemDiscover
from e_graph.models.section import ORDER, Section
from e_graph.pipelines.base import PipelineRegistry


async def test_the_system_passes_its_static_check() -> None:
    report = await SystemDiscover(await PipelineRegistry().mounts()).check()
    assert (report.ok, report.breaches) == (True, ()), [f"{b.rule} {b.subject}: {b.detail}" for b in report.breaches]
    assert report.pipelines == ("doc", "filing", "note")


def test_sections_keep_their_fixed_order() -> None:
    assert [section.value for section in ORDER][:2] == ["ingest", "normalize"]
    assert ORDER[-1] is Section.REPORT
