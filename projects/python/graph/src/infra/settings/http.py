"""infra/settings/http: the outbound HTTP edge — HTTP_BASE_URL, HTTP_TIMEOUT."""

from datetime import timedelta

from infra.settings.base import BaseSettings


class HttpSettings(BaseSettings):
    """HTTP_BASE_URL / HTTP_TIMEOUT (`timedelta`: plain seconds in config file or kwargs, `PT12.5S` in env)."""

    http_base_url: str = "https://httpbin.org"
    http_timeout: timedelta = timedelta(seconds=10)
