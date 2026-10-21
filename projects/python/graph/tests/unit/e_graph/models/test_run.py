"""tests/unit: models.run — the request seeds the run's data zone, empty by default."""

import msgspec

from e_graph.models.run import RunRequest


def test_run_request_defaults_empty() -> None:
    assert msgspec.json.decode(b"{}", type=RunRequest).data == {}


def test_run_request_carries_data() -> None:
    assert msgspec.json.decode(b'{"data": {"pace": 0.2}}', type=RunRequest).data == {"pace": 0.2}
