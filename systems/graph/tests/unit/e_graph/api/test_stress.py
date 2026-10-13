"""tests/unit: concurrent load on the live app — runs and health survive a burst; `make stress` soaks it."""

import asyncio

import pytest
from litestar.testing import AsyncTestClient

from e_graph.main import create_app

ACTORS: int = 8
HEALTH_BURST: int = 50


@pytest.mark.stress
async def test_api_survives_concurrent_traffic() -> None:
    """Eight runs at once, each over its own document, while health is hammered: no crosstalk between RunStates."""

    async def actor(client: AsyncTestClient, i: int) -> None:
        response = await client.post(
            "/api/pipelines/batch/doc", json={"data": {"document": f"invoice {i} total {i}.25"}}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["end"]["status"] == "succeeded"
        assert body["outputs"][3]["summary"] == f"attempt 1: amount {i}.25"

    async def health_burst(client: AsyncTestClient) -> None:
        responses = await asyncio.gather(*(client.get("/health") for _ in range(HEALTH_BURST)))
        assert [r.status_code for r in responses] == [200] * HEALTH_BURST

    async with AsyncTestClient(create_app()) as client, asyncio.TaskGroup() as group:
        for i in range(ACTORS):
            group.create_task(actor(client, i))
        group.create_task(health_burst(client))
