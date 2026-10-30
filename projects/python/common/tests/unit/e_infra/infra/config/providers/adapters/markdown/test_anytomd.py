"""tests/unit/e_infra/infra/config/providers/adapters/markdown/anytomd: AnytomdSettings — the converter, its PDF reader and its vision model."""

from typing import TYPE_CHECKING

from e_infra.infra.config.providers.adapters.markdown.anytomd import AnytomdSettings

if TYPE_CHECKING:
    import pytest


def test_anytomd_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = AnytomdSettings()
    assert (conf.vision_api_key, conf.image_describe, conf.pdf_ocr, conf.strict) == (None, True, False, False)
    monkeypatch.setenv("MD_VISION_API_KEY", "hunter2")
    monkeypatch.setenv("MD_PDF_OCR", "true")
    conf = AnytomdSettings()
    assert conf.vision_api_key is not None
    assert (conf.vision_api_key.get_secret_value(), conf.pdf_ocr) == ("hunter2", True)
    assert "hunter2" not in repr(conf)
