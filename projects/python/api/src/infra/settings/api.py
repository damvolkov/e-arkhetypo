"""infra/settings/api: the HTTP edge of this app — ALLOW_ORIGINS, ALLOW_METHODS."""

from enum import StrEnum

from pydantic import Field

from infra.settings.base import BaseSettings


##### ENUMS #####
class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"


##### DEFAULTS #####
DEFAULT_ORIGINS: list[str] = ["*"]
DEFAULT_METHODS: list[HttpMethod] = [HttpMethod.GET, HttpMethod.POST, HttpMethod.PATCH, HttpMethod.DELETE]


class ApiSettings(BaseSettings):
    """ALLOW_ORIGINS / ALLOW_METHODS — JSON lists via env or config file; verbs validated on decode."""

    allow_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_ORIGINS))
    allow_methods: list[HttpMethod] = Field(default_factory=lambda: list(DEFAULT_METHODS))
