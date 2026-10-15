"""tests/acceptance: the canvas as a user meets it — pipeline picker, live toasts, the closing modal, pinned PNGs.

Chromium drives the static page the app serves, which talks to the API exactly as any client would.
syrupy pins the screenshots pixel for pixel within the rendering tolerance measured in the conftest;
animations are frozen and run-dependent text (latencies, trace ids, the verdict's milliseconds) is
masked (`.stage-meta`), so a drift means the drawing changed. Async end to end on the session loop Playwright lives on.
Accepting a new picture is a human act: `make snap`, review, commit."""

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.async_api import Page, expect

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

pytestmark = pytest.mark.ui

NODES: int = 7
RUN_MS: float = 15_000
SIM_MS: float = 90_000
NOTES: Path = Path(__file__).resolve().parents[3] / "tests/resources/documents/notes/bofa-autocall-2027.pdf"
### a toast lives `toast_ms`; the margin covers the last one landing right before the verdict.
MARGIN_MS: float = 2_000


@pytest.fixture
async def canvas(page: Page, live_url: str) -> Page:
    """The canvas at a fixed viewport, the first pipeline picked and its whole topology drawn."""
    await page.set_viewport_size({"width": 1280, "height": 900})
    await page.goto(live_url)
    await expect(page.locator(".react-flow__node")).to_have_count(NODES)
    return page


async def shoot(page: Page) -> bytes:
    """The viewport with animations frozen and run-dependent text masked."""
    return await page.screenshot(animations="disabled", caret="hide", mask=[page.locator(".stage-meta")])


async def run(page: Page, verdict: str, toast_ms: int) -> None:
    """Press run, wait for the closing modal's verdict, then for every toast to expire."""
    await page.get_by_role("button", name="run").click()
    await expect(page.get_by_role("dialog", name="run outcome").locator(".verdict")).to_have_text(
        re.compile(rf"^{verdict}"), timeout=RUN_MS
    )
    await expect(page.locator(".toast")).to_have_count(0, timeout=toast_ms + MARGIN_MS)
    await page.mouse.move(0, 0)


async def test_picker_lists_the_discovered_pipelines(canvas: Page) -> None:
    await expect(canvas.get_by_label("pipeline")).to_have_value("doc")
    await expect(canvas.locator("select option")).to_have_text(["doc", "filing", "note"])
    await expect(canvas.locator(".pipeline-summary")).to_contain_text("Document intake")


async def test_the_pipeline_seed_arrives_with_the_pick(canvas: Page) -> None:
    """Choosing a pipeline loads its default seed: the note path is in the textarea before anyone types,
    and running the doc out of the box reaches a succeeded verdict — the canvas must never need a paste."""
    await canvas.get_by_label("pipeline").select_option("note")
    await expect(canvas.locator("textarea")).to_have_value(
        '{"source":"tests/resources/documents/notes/bofa-autocall-2027.pdf"}'
    )
    await canvas.get_by_label("pipeline").select_option("doc")
    await expect(canvas.locator("textarea")).to_have_value('{"document":"invoice 8 total 2.50"}')
    await canvas.evaluate("window.localStorage.clear()")
    await canvas.get_by_role("button", name="run").click()
    await expect(canvas.locator(".toast.status-succeeded").last).to_be_visible(timeout=RUN_MS)
    await canvas.evaluate("window.localStorage.clear()")


async def test_an_empty_data_is_refused_before_the_wire(canvas: Page) -> None:
    """Filing needs a `source`: clearing the data and running names what is missing without starting a run."""
    await canvas.get_by_label("pipeline").select_option("filing")
    await canvas.locator("textarea").fill("{}")
    await canvas.get_by_role("button", name="run").click()
    await expect(canvas.locator(".panel-error")).to_contain_text("data lacks source")
    await canvas.evaluate("window.localStorage.clear()")


async def test_the_data_seed_survives_the_panel_unmounting(canvas: Page) -> None:
    """The seed is typed once: visiting the specs level remounts the panel, and a lost paste is the run
    dying on an empty `source`. The textarea must come back with what was written."""
    seed = '{"source": "somewhere.pdf"}'
    await canvas.get_by_label("pipeline").select_option("note")
    await canvas.locator("textarea").fill(seed)
    await canvas.get_by_role("tab", name="specs").click()
    await canvas.get_by_role("tab", name="pipeline").click()
    await expect(canvas.locator("textarea")).to_have_value(seed)
    await canvas.evaluate("window.localStorage.clear()")


async def test_roles_mark_entry_and_exit(canvas: Page) -> None:
    await expect(canvas.locator(".stage.role-start")).to_have_text(re.compile(r"ingest"))
    await expect(canvas.locator(".stage.role-end")).to_have_text(re.compile(r"report"))


async def test_toasts_follow_the_run_then_expire(canvas: Page, toast_ms: int) -> None:
    await canvas.get_by_role("button", name="run").click()
    await expect(canvas.locator(".toast.status-succeeded").first).to_be_visible(timeout=RUN_MS)
    await expect(canvas.get_by_role("dialog", name="run outcome")).to_be_visible(timeout=RUN_MS)
    await expect(canvas.locator(".toast")).to_have_count(0, timeout=toast_ms + MARGIN_MS)


async def test_closing_modal_shows_the_end_node(canvas: Page, toast_ms: int) -> None:
    await run(canvas, "succeeded", toast_ms)
    modal = canvas.get_by_role("dialog", name="run outcome")
    await expect(modal.locator("dd").first).to_contain_text("report")
    await expect(modal).to_contain_text("delivered")
    await modal.get_by_role("button", name="close").click()
    await expect(modal).to_have_count(0)


async def test_failed_run_modal_shows_the_failure(canvas: Page, toast_ms: int) -> None:
    await canvas.get_by_label("inject failure").check()
    await run(canvas, "failed", toast_ms)
    modal = canvas.get_by_role("dialog", name="run outcome")
    await expect(modal).to_contain_text("extraction failed on purpose")
    await expect(modal).to_contain_text("skipped: validate, transform, report")


async def test_canvas_idle(canvas: Page, snapshot_png: SnapshotAssertion) -> None:
    assert await shoot(canvas) == snapshot_png


async def test_canvas_run_succeeded(canvas: Page, snapshot_png: SnapshotAssertion, toast_ms: int) -> None:
    await run(canvas, "succeeded", toast_ms)
    await expect(canvas.locator(".stage.status-skipped")).to_have_count(0)
    assert await shoot(canvas) == snapshot_png


async def test_canvas_run_failed(canvas: Page, snapshot_png: SnapshotAssertion, toast_ms: int) -> None:
    await canvas.get_by_label("inject failure").check()
    await run(canvas, "failed", toast_ms)
    await expect(canvas.locator(".stage.status-skipped")).to_have_count(3)
    assert await shoot(canvas) == snapshot_png


##### SPEC-NODE LEVEL #####
async def specs(page: Page, pipeline: str, section: str) -> Page:
    """The specs level, a pipeline's section picked and its spec-graph drawn."""
    await page.get_by_role("tab", name="specs").click()
    await page.get_by_label("spec pipeline").select_option(pipeline)
    await page.get_by_label("section").select_option(section)
    await expect(page.locator(".pipeline-summary")).to_contain_text("specs ·")
    return page


async def test_a_double_click_opens_the_nodes_spec_graph(canvas: Page) -> None:
    await canvas.get_by_label("pipeline").select_option("filing")
    await canvas.locator(".stage", has_text="extract").dblclick()
    await expect(canvas.get_by_role("tab", name="specs")).to_have_attribute("aria-selected", "true")
    await expect(canvas.locator(".spec")).to_have_count(3)
    await expect(canvas.locator(".call")).to_have_text(re.compile(r"call-0 · medium"))
    await expect(canvas.get_by_label("section")).to_have_value("extract")


async def test_a_spec_opens_its_card(canvas: Page) -> None:
    await specs(canvas, "filing", "extract")
    await canvas.locator(".spec", has_text="EXT-income").click()
    card = canvas.get_by_role("dialog", name="EXT-income")
    await expect(card).to_contain_text("post")
    await expect(card).to_contain_text("agnostic/number/scale")
    await expect(card).to_contain_text("output schema")


async def test_a_rehearsal_lights_the_section_and_shows_what_it_wrote(canvas: Page) -> None:
    await specs(canvas, "doc", "report")
    await canvas.get_by_label("data").fill('{"document": "invoice 8 total 2.50"}')
    await canvas.get_by_role("button", name="simulate").click()
    await expect(canvas.locator(".spec.status-succeeded")).to_have_count(1, timeout=RUN_MS)
    await expect(canvas.locator(".runs")).to_contain_text("transform: 1 specs")
    await canvas.locator(".spec", has_text="REP-serial").click()
    await expect(canvas.get_by_role("dialog", name="REP-serial")).to_contain_text("2.50")


async def test_bad_data_is_named_before_anything_runs(canvas: Page) -> None:
    await specs(canvas, "doc", "ingest")
    await canvas.get_by_label("data").fill("{nope")
    await canvas.get_by_role("button", name="simulate").click()
    await expect(canvas.locator(".panel-error")).to_contain_text("data is no JSON")


async def test_specs_idle(canvas: Page, snapshot_png: SnapshotAssertion) -> None:
    await specs(canvas, "filing", "extract")
    await canvas.mouse.move(0, 0)
    assert await shoot(canvas) == snapshot_png


async def test_the_runs_data_reaches_the_pipeline(canvas: Page, toast_ms: int) -> None:
    await canvas.get_by_label("data").fill('{"document": "receipt without total"}')
    await run(canvas, "failed", toast_ms)
    await expect(canvas.get_by_role("dialog", name="run outcome")).to_contain_text("transform")


async def test_bad_run_data_is_named_before_anything_runs(canvas: Page) -> None:
    await canvas.get_by_label("data").fill("{nope")
    await canvas.get_by_role("button", name="run").click()
    await expect(canvas.locator(".panel-error")).to_contain_text("data is no JSON")


async def test_the_note_extract_map_is_placed_wide_and_readable(canvas: Page, snapshot_png: SnapshotAssertion) -> None:
    """Every spec of the note's widest section at its step and lane — the PNG is the review of the width."""
    await specs(canvas, "note", "extract")
    await expect(canvas.locator(".spec")).to_have_count(22)
    assert await canvas.screenshot() == snapshot_png


async def test_a_rehearsed_medium_call_shows_its_merged_schema(canvas: Page) -> None:
    await specs(canvas, "note", "extract")
    await canvas.get_by_label("data").fill(json.dumps({"source": str(NOTES)}))
    await canvas.get_by_role("button", name="simulate").click()
    ### ten, not the five of the plan: the material re-splits the medium and low calls at the run.
    ### the acceptance server reads the PDF through the live docling: the rehearsal needs a minute, not a flash.
    await expect(canvas.locator(".call-chip")).to_have_count(10, timeout=SIM_MS)
    await canvas.locator(".call-chip").filter(has_text=re.compile("medium")).first.click()
    card = canvas.get_by_role("dialog")
    await card.get_by_role("tab", name="schema").click()
    await expect(card).to_contain_text('"title": "fused"')
    await expect(card).to_contain_text('"EXT-')
