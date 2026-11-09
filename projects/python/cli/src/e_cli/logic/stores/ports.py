"""logic.stores.ports: the business stores as the commands see them — the login and the projects, by shape.

A command declares `Inject[ProjectStorePort]`; the composition root (`runtime.deps`) answers with the store it built,
and a test with a fake of the same shape."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_cli.models.project import ProjectState

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from e_cli.models.identity import Identity
    from e_cli.models.project import Project


@runtime_checkable
class AuthStorePort(Protocol):
    """The stored login, and who a run acts as."""

    async def login(self, token: str) -> Identity: ...

    async def logout(self) -> None: ...

    async def identify(self, given: Identity | None) -> Identity: ...


@runtime_checkable
class ProjectStorePort(Protocol):
    """Create, read, change and delete projects."""

    async def get(self, name: str) -> Project: ...

    def listing(self) -> AsyncIterator[Project]: ...

    async def create(self, name: str, description: str = "", state: ProjectState = ProjectState.DRAFT) -> Project: ...

    async def remove(self, name: str) -> Project: ...

    async def assign(self, name: str, key: str, value: str) -> Project: ...
