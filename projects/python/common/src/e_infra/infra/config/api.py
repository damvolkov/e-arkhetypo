"""infra/config/api: the HTTP edge of this app — ALLOW_ORIGINS, ALLOW_METHODS."""

from enum import StrEnum

from pydantic import Field

from e_infra.infra.config.base import BaseSettings


##### ENUMS #####
class HTTPMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"


##### DEFAULTS #####
DEFAULT_ORIGINS: list[str] = ["*"]
DEFAULT_METHODS: list[HTTPMethod] = [HTTPMethod.GET, HTTPMethod.POST, HTTPMethod.PATCH, HTTPMethod.DELETE]


class APISettings(BaseSettings):
    """ALLOW_ORIGINS / ALLOW_METHODS — JSON lists via env or config file; verbs validated on decode."""

    allow_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_ORIGINS))
    allow_methods: list[HTTPMethod] = Field(default_factory=lambda: list(DEFAULT_METHODS))
