"""tests/acceptance: the canvas as a user meets it — pipeline picker, live toasts, the closing modal, pinned PNGs.

Chromium drives the static page the app serves, which talks to the API exactly as any client would.
syrupy pins the screenshots pixel for pixel within the rendering tolerance measured in the conftest;
animations are frozen and run-dependent text (latencies, trace ids, the verdict's milliseconds) is
masked (`.stage-meta`), so a drift means the drawing changed. Async end to end on the session loop Playwright lives on.
Accepting a new picture is a human act: `make snap`, review, commit."""

import re
from typing import TYPE_CHECKING

import pytest
from playwright.async_api import Page, expect

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

pytestmark = pytest.mark.ui

NODES: int = 7
RUN_MS: float = 15_000
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
    await expect(canvas.locator("select option")).to_have_text(["doc"])
    await expect(canvas.locator(".pipeline-summary")).to_contain_text("Document intake")


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
