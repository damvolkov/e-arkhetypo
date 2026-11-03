"""infra/config/processors/md: the Markdown processor — input ceiling, ZIP fan-out and its zip-bomb guard (MD_*)."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


##### SETTINGS #####
class MDSettings(BaseSettings):
    """MD_MAX_INPUT_BYTES — refuse before converting; MD_CONCURRENCY — files rendered at once inside a ZIP;
    MD_ZIP_MAX_ENTRIES / MD_ZIP_MAX_BYTES — the fan-out's zip-bomb guard."""

    model_config = SettingsConfigDict(env_prefix="MD_")

    max_input_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    concurrency: int = Field(default=8, ge=1)
    zip_max_entries: int = Field(default=1024, ge=1)
    zip_max_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
