"""infra/config/api: the HTTP edge of this app — CORS, and where the OpenAPI pages live."""

from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from e_infra.infra.config.base import BaseSettings


##### ENUMS #####
class HTTPMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"


class DocsRenderer(StrEnum):
    """An OpenAPI page an API can serve; the value is its subpath under the docs root."""

    SWAGGER = "swagger"
    REDOC = "redoc"
    ELEMENTS = "elements"
    RAPIDOC = "rapidoc"
    SCALAR = "scalar"


##### SETTINGS #####
class ApiSettings(BaseSettings):
    """The HTTP edge: lists decode from JSON in env (`DOCS_ALIASES='["/schema", "/api/docs"]'`). The docs are validated
    on load: absolute paths, no alias repeating the root, at least one renderer."""

    ### CORS
    ALLOW_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])
    ALLOW_METHODS: list[HTTPMethod] = Field(
        default_factory=lambda: [HTTPMethod.GET, HTTPMethod.POST, HTTPMethod.PATCH, HTTPMethod.DELETE]
    )

    ### DOCS
    ### the canonical docs root.
    DOCS_PATH: str = "/docs"
    ### extra roots that redirect there, subpath kept.
    DOCS_ALIASES: list[str] = Field(default_factory=lambda: ["/schema"])
    ### the pages served, the first one at the root itself.
    DOCS_RENDERERS: list[DocsRenderer] = Field(
        default_factory=lambda: [DocsRenderer.SWAGGER, DocsRenderer.REDOC, DocsRenderer.ELEMENTS, DocsRenderer.RAPIDOC],
        min_length=1,
    )

    @field_validator("DOCS_PATH")
    @classmethod
    def _docs_absolute(cls, value: str) -> str:
        match value.startswith("/"):
            case True:
                ### one canonical spelling: `/docs`, never `/docs/` — subpaths are appended to it.
                return value.rstrip("/") or "/"
            case _:
                msg = f"docs path must be absolute: {value!r}"
                raise ValueError(msg)

    @field_validator("DOCS_ALIASES")
    @classmethod
    def _docs_aliases_absolute(cls, value: list[str]) -> list[str]:
        match [alias for alias in value if not alias.startswith("/")]:
            case []:
                return [alias.rstrip("/") for alias in value]
            case relative:
                msg = f"docs aliases must be absolute: {relative}"
                raise ValueError(msg)

    @model_validator(mode="after")
    def _docs_aliases_elsewhere(self) -> Self:
        match self.DOCS_PATH in self.DOCS_ALIASES:
            case True:
                msg = f"an alias cannot be the docs root itself: {self.DOCS_PATH!r}"
                raise ValueError(msg)
            case _:
                return self
