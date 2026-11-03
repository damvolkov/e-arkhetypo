"""infra/config/providers/adapters/language/lingua: which languages the detector may answer (LANGUAGE_*)."""

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class LinguaSettings(BaseSettings):
    """LANGUAGE_LANGUAGES — the ISO 639-1 codes the detector chooses among, as JSON (`["en", "es"]`): a closed set,
    smaller is faster and surer; a text in another language is answered as the nearest of them."""

    model_config = SettingsConfigDict(env_prefix="LANGUAGE_")

    languages: tuple[str, ...] = ("en", "es")
