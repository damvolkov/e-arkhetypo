"""tests/unit: concurrent load on the live app — chains, graph and seal survive a burst; `make stress` soaks it."""

import asyncio
from datetime import timedelta

import pytest
from litestar.testing import AsyncTestClient

from e_api.main import create_app

ACTORS: int = 8
HEALTH_BURST: int = 50


@pytest.mark.stress
async def test_api_survives_concurrent_traffic() -> None:
    """Eight actors run the full user flow at once while health is hammered: no crosstalk, no failure."""

    async def actor(client: AsyncTestClient, i: int) -> None:
        created = await client.post(
            "/users",
            json={"username": f"user{i}", "email": f"user{i}@stress.test", "password": "s3cret-passphrase"},
        )
        assert created.status_code == 201
        user_id = created.json()["id"]
        token = client.app.state.system.crypto.create_token({"sub": user_id}, expires_in=timedelta(minutes=1))
        headers = {"Authorization": f"Bearer {token}"}

        read = await client.get(f"/users/{user_id}", headers=headers)
        assert read.status_code == 200
        assert read.json()["username"] == f"user{i}"

        patched = await client.patch(f"/users/{user_id}", json={"quota": f"0.{i:02d}"}, headers=headers)
        assert patched.status_code == 200
        assert patched.json()["quota"] == f"0.{i:02d}"

    async def health_burst(client: AsyncTestClient) -> None:
        responses = await asyncio.gather(*(client.get("/health") for _ in range(HEALTH_BURST)))
        assert [r.status_code for r in responses] == [200] * HEALTH_BURST

    async with AsyncTestClient(create_app()) as client, asyncio.TaskGroup() as group:
        for i in range(ACTORS):
            group.create_task(actor(client, i))
        group.create_task(health_burst(client))
