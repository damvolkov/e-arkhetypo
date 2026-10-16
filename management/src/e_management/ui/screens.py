"""ui.screens: the three machines around the walk — the generation log, the verdict, the read-only map.

The wizard itself is a `WizardApp` flow; these are plain screens it pushes: the pipeline streaming
every emitted line, the report with the way back, and the dependency overlay opened with `g`. Nothing
here decides anything — they show what the engine and the graph already said."""

from typing import TYPE_CHECKING

from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

##### STYLES #####
LOG_STYLE = "color: #c9d1d9"

##### SCREENS #####


class ProgressScreen(Screen[None]):
    """The pipeline's log: every emitted line of every step, streaming while generation and verification run."""

    DEFAULT_CSS = """
    ProgressScreen { background: #04060b; }
    ProgressScreen > VerticalScroll { border: round #1a2b55; margin: 1 2; padding: 0 1; background: #03050a; }
    ProgressScreen #note { color: #56627a; margin: 1 2 0 2; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def compose(self) -> Any:
        yield Static("generating — ctrl+q quits; the draft survives", id="note")
        with VerticalScroll():
            yield Static("", id="log")

    async def line(self, text: str) -> None:
        """Append one emitted line and follow it: the log is only ever worth reading at its end."""
        self.lines.append(text)
        self.query_one("#log", Static).update("\n".join(self.lines))
        self.query_one(VerticalScroll).scroll_end(animate=False)


class ReportScreen(Screen[None]):
    """The verdict: ready to work — or the failed steps, verbatim, with a way back to fix and retry."""

    DEFAULT_CSS = """
    ReportScreen { background: #04060b; }
    ReportScreen > VerticalScroll { border: round #1a2b55; margin: 1 2; padding: 0 1; background: #03050a; }
    ReportScreen .actions { dock: bottom; height: auto; align-horizontal: right; padding-bottom: 1; }
    """

    def __init__(self, *, ok: bool, dest: Path, failures: list[str]) -> None:
        super().__init__()
        self.ok, self.dest, self.failures = ok, dest, failures

    def compose(self) -> Any:
        verdict = (
            f"✓ {self.dest} is ready to work — cd in and start"
            if self.ok
            else "✗ stopped:\n" + "\n".join(self.failures[-40:])
        )
        with VerticalScroll():
            yield Static(verdict, id="verdict")
        with Horizontal(classes="actions"):
            yield (
                Button("finish", id="finish", variant="primary")
                if self.ok
                else Button("←  back to review", id="retry", variant="warning")
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "finish":
                self.app.exit()
            case _:
                self.app.pop_screen()


class GraphScreen(Screen[None]):
    """A read-only inspector of the live dependency map, opened with `g` — never a step of the wizard."""

    DEFAULT_CSS = """
    GraphScreen { background: #04060b; }
    GraphScreen > VerticalScroll { border: round #1a2b55; margin: 1 2; padding: 0 1; background: #03050a; }
    GraphScreen #note { color: #56627a; margin: 1 2 0 2; }
    """

    def __init__(self, text: Any) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> Any:
        yield Static("read-only  ·  AST imports + graphlib levels  ·  esc to go back", id="note")
        with VerticalScroll():
            yield Static(self._text)

    def key_escape(self, _event: Any) -> None:
        """The overlay dismisses itself — `g` opens a look, not a step."""
        self.app.pop_screen()
