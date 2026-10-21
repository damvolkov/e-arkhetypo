"""tests/acceptance/e_graph: the app as a user meets it — granian serving the built canvas on a free port.

The page under test is the static bundle the app itself serves at `/` (`make bundle` produces it);
the server is the production one, a real process on a real socket, so the websocket run is the real
run. One server per session (per xdist worker), torn down with it."""

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PIL import Image, ImageChops
from syrupy.extensions.image import PNGImageSnapshotExtension

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syrupy.assertion import SnapshotAssertion
    from syrupy.types import SerializableData

ROOT: Path = Path(__file__).resolve().parents[3]
BUNDLE: Path = ROOT / "src" / "e_graph" / "ui" / "dist" / "index.html"
BOOT_SECONDS: float = 20.0
TOAST_SECONDS: float = 0.6
### measured: chromium's compositor moves anti-aliased edges and blurred shadows by at most 5/255 between
### identical renders; a real drawing change (a status colour, a moved node, a glyph) moves hundreds.
TOLERANCE: int = 16


class TolerantPNGExtension(PNGImageSnapshotExtension):
    """PNG snapshots compared by pixels, not bytes: a per-channel delta up to TOLERANCE is rendering noise."""

    def matches(self, *, serialized_data: SerializableData, snapshot_data: SerializableData) -> bool:
        received, stored = (Image.open(io.BytesIO(raw)).convert("RGB") for raw in (serialized_data, snapshot_data))
        ### a 256-entry lookup per channel zeroes every delta within tolerance; an empty bbox means nothing is left.
        ### the size check short-circuits first: Pillow refuses to diff images of different sizes.
        return (
            received.size == stored.size
            and ImageChops.difference(received, stored).point(lambda delta: 255 if delta > TOLERANCE else 0).getbbox()
            is None
        )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def live_url() -> Iterator[str]:
    """Base URL of a live granian serving the app and its canvas; fails loudly when the canvas is unbuilt."""
    match BUNDLE.is_file():
        case False:
            pytest.fail("canvas bundle missing: run `make bundle` before the ui tests")
        case _:
            pass
    port, scratch = free_port(), tempfile.mkdtemp(prefix="e-graph-ui-")
    env = os.environ | {
        "PYTHONPATH": str(ROOT / "src"),
        "CRYPTO__SECRET": "ui-test-secret-0123456789",  # gitleaks:allow
        "DB_PATH": f"{scratch}/ui.db",
    }
    command = [sys.executable, "-m", "granian", "--interface", "asgi", "--factory", "--host", "127.0.0.1"]
    ### a fixed argv over our own interpreter and module, no shell, no user input.
    server = subprocess.Popen(  # noqa: S603
        [*command, "--port", str(port), "e_graph.main:create_app"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + BOOT_SECONDS
    while not _alive(url) and time.monotonic() < deadline and server.poll() is None:
        time.sleep(0.1)
    try:
        assert _alive(url), "granian never answered /health"
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(scope="session")
def toast_ms(live_url: str) -> int:
    """The toast lifetime as the canvas itself reads it: from the API, never from a constant shared with tests."""
    ### loopback http to the server this session started — the scheme is ours, not an input.
    with urllib.request.urlopen(f"{live_url}/api/ui", timeout=2) as response:  # noqa: S310
        return int(json.loads(response.read())["toast_ms"])


def _alive(url: str) -> bool:
    try:
        ### loopback http to the server this fixture started — the scheme is ours, not an input.
        with urllib.request.urlopen(f"{url}/health", timeout=1) as response:  # noqa: S310
            return response.status == 200
    except OSError:
        return False


@pytest.fixture
def snapshot_png(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """syrupy's PNG snapshot, compared within the rendering tolerance."""
    return snapshot.use_extension(TolerantPNGExtension)
