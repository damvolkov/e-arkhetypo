"""tests/unit/e_infra/infra/config/providers/adapters/pages/liteparse: LiteparseSettings — its Tesseract and its page workers."""

from pathlib import Path
from typing import TYPE_CHECKING

from e_infra.infra.config.providers.adapters.pages.liteparse import LiteparseSettings

if TYPE_CHECKING:
    import pytest


def test_liteparse_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = LiteparseSettings()
    assert (conf.ocr, conf.tessdata, conf.ocr_language, conf.workers) == (False, None, "eng", 0)
    monkeypatch.setenv("DOC_TESSDATA", "/usr/share/tessdata")
    monkeypatch.setenv("DOC_WORKERS", "4")
    conf = LiteparseSettings()
    assert (conf.tessdata, conf.workers) == (Path("/usr/share/tessdata"), 4)
