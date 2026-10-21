"""tests/unit: telemetry models — the latency-to-status bands."""

import pytest

from e_api.models.telemetry import DOWN_MS, LAG_MS, Status


@pytest.mark.parametrize(
    ("ms", "band"),
    [
        (0.0, Status.OK),
        (LAG_MS - 0.01, Status.OK),
        (LAG_MS, Status.LAG),
        (DOWN_MS - 0.01, Status.LAG),
        (DOWN_MS, Status.DOWN),
        (10_000.0, Status.DOWN),
    ],
)
def test_status_bands(ms: float, band: Status) -> None:
    assert Status.from_latency(ms) is band
