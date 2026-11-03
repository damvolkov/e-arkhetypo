"""infra/config/providers/drivers/http/wreq: the outbound HTTP client — base, timeout, agent and headers."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class WreqSettings(BaseSettings):
    """HTTP_BASE_URL — joined to a relative path; HTTP_TIMEOUT — a request unless the call names its own (`timedelta`:
    plain seconds in config file or kwargs, `PT12.5S` in env); HTTP_AGENT — the User-Agent of every request, who asks
    and where to reach whoever runs it (sites that serve robots ask for one: Wikimedia answers 403 without);
    HTTP_HEADERS — sent with every request of the process, to every service it reaches: never a credential of one
    service, which travels per call (`headers=`) so it cannot leak to the others."""

    model_config = SettingsConfigDict(env_prefix="HTTP_")

    base_url: str = "https://httpbin.org"
    timeout: timedelta = timedelta(seconds=10)
    agent: str = "e-infra/1 (+https://github.com/damvolkov/e-arkhetypo)"
    headers: dict[str, str] = Field(default_factory=dict)
