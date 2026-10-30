"""tests/unit/e_infra/infra/config/providers/drivers/documents/docling: DoclingSettings — the server, its bounds and its conversion."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.documents.docling import DoclingFormat, DoclingSettings, DoclingTables


def test_docling_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = DoclingSettings()
    assert (conf.timeout, conf.deadline, conf.tables) == (
        timedelta(seconds=60),
        timedelta(minutes=15),
        DoclingTables.ACCURATE,
    )
    monkeypatch.setenv("DOCLING_URL", "http://docling:5001")
    monkeypatch.setenv("DOCLING_FORMATS", '["md"]')
    conf = DoclingSettings()
    assert (conf.url, conf.formats) == ("http://docling:5001", (DoclingFormat.MD,))


def test_docling_images_scale_is_positive() -> None:
    with pytest.raises(ValidationError):
        DoclingSettings(images_scale=0)
