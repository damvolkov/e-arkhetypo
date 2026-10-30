"""infra/config/docs: where the OpenAPI pages live, which aliases lead there, which renderers serve (DOCS_*)."""

from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


##### ENUMS #####
class DocsRenderer(StrEnum):
    """An OpenAPI page an API can serve; the value is its subpath under the docs root."""

    SWAGGER = "swagger"
    REDOC = "redoc"
    ELEMENTS = "elements"
    RAPIDOC = "rapidoc"
    SCALAR = "scalar"


##### SETTINGS #####
class DocsSettings(BaseSettings):
    """DOCS_PATH — the canonical docs root; DOCS_ALIASES — extra roots that redirect there, subpath kept;
    DOCS_RENDERERS — the pages served, the first one at the root itself. Lists decode from JSON in env:
    `DOCS_ALIASES='["/schema", "/api/docs"]'`. Validated on load: absolute paths, no alias repeating
    the root, at least one renderer."""

    model_config = SettingsConfigDict(env_prefix="DOCS_")

    path: str = "/docs"
    aliases: list[str] = Field(default_factory=lambda: ["/schema"])
    renderers: list[DocsRenderer] = Field(
        default_factory=lambda: [DocsRenderer.SWAGGER, DocsRenderer.REDOC, DocsRenderer.ELEMENTS, DocsRenderer.RAPIDOC],
        min_length=1,
    )

    @field_validator("path")
    @classmethod
    def _absolute_root(cls, value: str) -> str:
        match value.startswith("/"):
            case True:
                ### one canonical spelling: `/docs`, never `/docs/` — subpaths are appended to it.
                return value.rstrip("/") or "/"
            case False:
                msg = f"docs path must be absolute: {value!r}"
                raise ValueError(msg)

    @field_validator("aliases")
    @classmethod
    def _absolute_aliases(cls, value: list[str]) -> list[str]:
        match [alias for alias in value if not alias.startswith("/")]:
            case []:
                return [alias.rstrip("/") for alias in value]
            case relative:
                msg = f"docs aliases must be absolute: {relative}"
                raise ValueError(msg)

    @model_validator(mode="after")
    def _aliases_elsewhere(self) -> Self:
        match self.path in self.aliases:
            case True:
                msg = f"an alias cannot be the docs root itself: {self.path!r}"
                raise ValueError(msg)
            case False:
                return self
