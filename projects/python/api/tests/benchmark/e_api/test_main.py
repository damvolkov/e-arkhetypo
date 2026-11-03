"""tests/benchmark/e_api/main: concurrent load on the app `create_app` builds — chains, graph and seal survive a burst;
`make stress` soaks it. Not a unit of one module: every layer answers at once, over the faked services of `tests/conftest`."""

import asyncio

import pytest
from litestar.testing import AsyncTestClient

from e_api.main import create_app

ADMIN: dict[str, str] = {"Authorization": "Bearer t-root"}
READER: dict[str, str] = {"Authorization": "Bearer t-ana"}
ACTORS: int = 8
HEALTH_BURST: int = 50


@pytest.mark.stress
async def test_create_app_stress_concurrent_traffic() -> None:
    """Eight actors run the full user flow at once, each key at its access, while health is hammered: no crosstalk."""

    async def actor(client: AsyncTestClient, i: int) -> None:
        created = await client.post(
            "/users",
            json={"username": f"user{i}", "email": f"user{i}@stress.test", "password": "s3cret-passphrase"},
            headers=ADMIN,
        )
        assert created.status_code == 201
        user_id = created.json()["id"]

        read = await client.get(f"/users/{user_id}", headers=READER)
        assert read.status_code == 200
        assert read.json()["username"] == f"user{i}"

        patched = await client.patch(f"/users/{user_id}", json={"quota": f"0.{i:02d}"}, headers=ADMIN)
        assert patched.status_code == 200
        assert patched.json()["quota"] == f"0.{i:02d}"

    async def health_burst(client: AsyncTestClient) -> None:
        responses = await asyncio.gather(*(client.get("/health") for _ in range(HEALTH_BURST)))
        assert [r.status_code for r in responses] == [200] * HEALTH_BURST

    async with AsyncTestClient(create_app()) as client, asyncio.TaskGroup() as group:
        for i in range(ACTORS):
            group.create_task(actor(client, i))
        group.create_task(health_burst(client))
