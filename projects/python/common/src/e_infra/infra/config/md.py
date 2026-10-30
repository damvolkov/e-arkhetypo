"""infra/config/md: the anytomd Markdown converter — its PDF and vision capabilities and the ZIP fan-out (MD_*)."""

from pydantic import Field

from e_infra.infra.config.base import BaseSettings, Secret


##### SETTINGS #####
class MDSettings(BaseSettings):
    """MD_STRICT / MD_EXTRACT_COMMENTS — anytomd's own switches; MD_MAX_INPUT_BYTES — refuse before converting;
    MD_PDF_OCR / MD_PDF_LANGUAGE / MD_PDF_WORKERS — the bundled liteparse PDF reader; MD_IMAGE_DESCRIBE — whether
    a vision model annotates images (their `alt`); MD_VISION_* — that model (OpenAI-compatible base, model, key,
    prompt); MD_CONCURRENCY — files rendered at once inside a ZIP; MD_ZIP_MAX_ENTRIES / MD_ZIP_MAX_BYTES — the
    fan-out's zip-bomb guard."""

    md_strict: bool = False
    md_extract_comments: bool = False
    md_max_input_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    md_pdf_ocr: bool = False
    md_pdf_language: str = "eng"
    md_pdf_workers: int = Field(default=0, ge=0)
    md_image_describe: bool = True
    md_vision_base_url: str = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    md_vision_model: str = "qwen3.8-flash"
    md_vision_api_key: Secret | None = None
    md_vision_prompt: str = "Describe this image for an AI agent in plain Markdown: what it shows, any text in it."
    md_concurrency: int = Field(default=8, ge=1)
    md_zip_max_entries: int = Field(default=1024, ge=1)
    md_zip_max_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
