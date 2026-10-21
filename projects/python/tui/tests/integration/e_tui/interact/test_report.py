"""tests/integration/e_tui/interact/report: a page to read commits instantly — it is seen, then passed."""

from e_tui.interact.report import Report
from e_tui.models.object import ReportSpec


async def test_report_commits_immediately(mount) -> None:
    app = mount(lambda: Report(ReportSpec(prompt="done", lines=("wrote 3 files", "built image"))))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit().ok


async def test_report_without_prompt_still_renders(mount) -> None:
    app = mount(lambda: Report(ReportSpec(lines=("only body",))))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit() is not None
