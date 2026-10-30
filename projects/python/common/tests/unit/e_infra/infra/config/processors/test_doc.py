"""tests/unit/e_infra/infra/config/processors/doc: DocSettings — which engine reads which page, and how hard to push."""

import pytest
from pydantic import ValidationError

from e_infra.infra.config.processors.doc import DocMode, DocSettings, DocSignal


def test_doc_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = DocSettings()
    assert (conf.mode, conf.span, conf.concurrency) == (DocMode.HYBRID, 64, 2)
    monkeypatch.setenv("DOC_MODE", "lite")
    monkeypatch.setenv("DOC_ROUTE", '["table"]')
    conf = DocSettings()
    assert (conf.mode, conf.route) == (DocMode.LITE, (DocSignal.TABLE,))


def test_doc_span_is_positive() -> None:
    with pytest.raises(ValidationError):
        DocSettings(span=0)
