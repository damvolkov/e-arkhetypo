"""tests/unit/e_graph/logic/orchestrator: a harness per test — a crafter's tree, the orchestrator over it, a scripted agent."""

from typing import TYPE_CHECKING

import pytest

from infra.config.providers.drivers.telemetry.otel import OtelSettings
from providers.drivers.telemetry.otel import OtelDriver
from support.crafter import SpecCrafter
from support.darts import DartsHarness

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from pytest_resources import Resources


@pytest.fixture
async def darts(resources: Resources, tmp_path: Path, exporter: InMemorySpanExporter) -> AsyncIterator[DartsHarness]:
    """A fresh `doc` pipeline under a temporary root, its spans readable in memory."""
    async with OtelDriver(OtelSettings(), exporter) as telemetry:
        yield DartsHarness(SpecCrafter(resources, tmp_path, seed=7), telemetry)
