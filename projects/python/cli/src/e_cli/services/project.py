"""services.project: the project use cases — the core of the demo domain, knowing the store only as a port.

`ProjectService` never names sqlite, redis or the journal: it asks a `StorePort` and gets whatever the
composition root bound (today, sqlite behind the undo journal). Raw user input enters through
`msgspec.convert` against the constrained models, so every rule in `models.project` runs once, here,
and a violation leaves as a `ProjectError` the launcher knows how to report."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import msgspec

from e_cli.models.error import ProjectError
from e_cli.models.project import EnvKey, Project, ProjectSpec, ProjectState

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from adapters.ports import StorePort

##### DEFAULTS #####
PREFIX: str = "project:"


##### TYPES #####
class ProjectService:
    """Create, read, change and delete projects over any `StorePort`."""

    __slots__ = ("_store",)

    def __init__(self, store: StorePort) -> None:
        self._store = store

    ##### PRIVATE METHODS #####

    @staticmethod
    def _create_spec(name: str, description: str, state: ProjectState) -> ProjectSpec:
        """The boundary: raw arguments converted against the constrained spec, or refused with the rule broken."""
        try:
            return msgspec.convert({"name": name, "description": description, "state": state}, ProjectSpec)
        except msgspec.ValidationError as exc:
            msg = f"invalid project: {exc}"
            raise ProjectError(msg) from exc

    @staticmethod
    def _assign_key(key: str) -> str:
        try:
            return msgspec.convert(key, EnvKey)
        except msgspec.ValidationError as exc:
            msg = f"invalid variable name {key!r}: {exc}"
            raise ProjectError(msg) from exc

    async def _common_save(self, project: Project) -> Project:
        await self._store.set(f"{PREFIX}{project.name}", msgspec.json.encode(project))
        return project

    ############################################################

    ##### PUBLIC #####

    async def get(self, name: str) -> Project:
        """The project named `name`, or the typed refusal every use case shares."""
        match await self._store.get(f"{PREFIX}{name}"):
            case None:
                msg = f"no project named {name!r}: `ecli project list` shows them"
                raise ProjectError(msg)
            case raw:
                return msgspec.json.decode(raw, type=Project)

    async def listing(self) -> AsyncIterator[Project]:
        """Every project, streamed in key order: nothing is collected the caller does not ask for."""
        async for key in self._store.keys(PREFIX):
            yield await self.get(key.removeprefix(PREFIX))

    async def create(self, name: str, description: str = "", state: ProjectState = ProjectState.DRAFT) -> Project:
        spec = self._create_spec(name, description, state)
        match await self._store.get(f"{PREFIX}{spec.name}"):
            case None:
                return await self._common_save(
                    Project(name=spec.name, description=spec.description, state=spec.state, created=datetime.now(UTC))
                )
            case _:
                msg = f"project {spec.name!r} already exists"
                raise ProjectError(msg)

    async def remove(self, name: str) -> Project:
        found = await self.get(name)
        await self._store.delete(f"{PREFIX}{name}")
        return found

    async def assign(self, name: str, key: str, value: str) -> Project:
        """Set one environment variable of a project; the key is validated as `EnvKey`."""
        found = await self.get(name)
        return await self._common_save(msgspec.structs.replace(found, env={**found.env, self._assign_key(key): value}))
