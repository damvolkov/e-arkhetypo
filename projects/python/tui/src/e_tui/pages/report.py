"""e_tui.pages.report: the terminal page — read it, then advance; the emitted model arrives behind it."""

from e_tui.flow.page import Page
from e_tui.models.object import ReportSpec

PAGE = Page(
    id="report",
    title="Report",
    spec=ReportSpec(prompt="review", lines=("press accept to emit the blueprint",)),
)
