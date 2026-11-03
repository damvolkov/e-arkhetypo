"""infra/config/providers/adapters/pages/liteparse: liteparse's own Tesseract and page workers (DOC_*)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class LiteparseSettings(BaseSettings):
    """DOC_WORKERS — liteparse's page workers (0: its default); DOC_OCR / DOC_TESSDATA / DOC_OCR_LANGUAGE — its own
    Tesseract, for scanned pages docling does not take (lite mode, or docling down)."""

    model_config = SettingsConfigDict(env_prefix="DOC_")

    workers: int = Field(default=0, ge=0)
    ocr: bool = False
    tessdata: Path | None = None
    ocr_language: str = "eng"
