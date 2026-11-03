"""infra/config/providers/adapters/markdown/anytomd: the anytomd converter — its PDF reader and the vision model (MD_*)."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret


##### SETTINGS #####
class AnytomdSettings(BaseSettings):
    """MD_VISION_BASE_URL / MD_VISION_API_KEY / MD_VISION_MODEL / MD_VISION_PROMPT — the OpenAI-compatible model that
    annotates images (their `alt`); MD_IMAGE_DESCRIBE — whether it is asked at all; MD_MAX_INPUT_BYTES — anytomd's own
    ceiling, as the processor's; MD_PDF_OCR / MD_PDF_LANGUAGE / MD_PDF_WORKERS — the bundled liteparse PDF reader;
    MD_STRICT / MD_EXTRACT_COMMENTS — anytomd's own switches."""

    model_config = SettingsConfigDict(env_prefix="MD_")

    vision_base_url: str = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    vision_api_key: Secret | None = None
    max_input_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    pdf_workers: int = Field(default=0, ge=0)
    vision_model: str = "qwen3.8-flash"
    vision_prompt: str = "Describe this image for an AI agent in plain Markdown: what it shows, any text in it."
    image_describe: bool = True
    pdf_ocr: bool = False
    pdf_language: str = "eng"
    strict: bool = False
    extract_comments: bool = False
