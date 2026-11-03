"""tests/unit/e_infra/providers/adapters/language/lingua: the language of a text, over a closed set of codes."""

import pickle
from importlib.metadata import version
from pathlib import Path
from typing import Final

import pytest

from e_infra.infra.config.providers.adapters.language.lingua import LinguaSettings
from e_infra.ports.language import LanguagePort
from e_infra.providers.adapters.language.lingua import LinguaAdapter

SAMPLES: Final[Path] = Path(__file__).resolve().parents[5] / "resources" / "language"
ES, EN, SHORT_TEXT = ((SAMPLES / f"{name}.md").read_text() for name in ("es", "en", "short"))


@pytest.fixture(scope="module")
def lingua() -> LinguaAdapter:
    return LinguaAdapter(LinguaSettings(languages=("en", "es")))


async def test_lingua_meets_the_port_and_its_lifecycle(lingua: LinguaAdapter) -> None:
    async with lingua as opened:
        assert (isinstance(opened, LanguagePort), await opened.health()) == (True, True)


@pytest.mark.parametrize(("text", "lang"), [(ES, "es"), (EN, "en")], ids=["es", "en"])
def test_lingua_detect(lingua: LinguaAdapter, text: str, lang: str) -> None:
    found = lingua.detect(text)
    assert found is not None
    assert (found[0], found[1] > 0.5) == (lang, True)


def test_lingua_detect_nothing(lingua: LinguaAdapter) -> None:
    assert lingua.detect("") is None


def test_lingua_each(lingua: LinguaAdapter) -> None:
    """Each text its own language; one too short to tell gets none, whatever lingua would guess."""
    assert lingua.each([ES, EN, SHORT_TEXT, ""]) == ["es", "en", "", ""]


def test_lingua_document_majority(lingua: LinguaAdapter) -> None:
    """A mixed document is in the language most of its characters are in — lingua over the joined text says English
    here, swayed by the English paragraph's telling words."""
    texts = [ES, EN, ES]
    found = lingua.document(texts, lingua.each(texts))
    assert found is not None
    assert (found[0], round(found[1], 2)) == ("es", round(2 * len(ES) / sum(map(len, texts)), 2))
    assert lingua.detect("\n".join(texts)) == ("en", pytest.approx(1.0))


def test_lingua_document_untold(lingua: LinguaAdapter) -> None:
    """No text long enough to tell: the joined text is read whole."""
    texts = [line for line in ES.split(", ") if line]
    found = lingua.document(texts, [""] * len(texts))
    assert found is not None
    assert found[0] == "es"


def test_lingua_restricted() -> None:
    """Only the configured languages are answered: Spanish text read by an English-only detector is English."""
    assert LinguaAdapter(LinguaSettings(languages=("en",))).each([ES]) == ["en"]


def test_lingua_annotator(lingua: LinguaAdapter) -> None:
    assert lingua.annotator == f"lingua@{version('lingua-language-detector')}"


def test_lingua_pickles_as_its_settings(lingua: LinguaAdapter) -> None:
    """Pickled, the detector travels as its settings and reads the same where it lands."""
    again = pickle.loads(pickle.dumps(lingua))  # noqa: S301 — our own object, round-tripped
    probe = "La reunión trata del presupuesto anual."
    assert (again.annotator, again.detect(probe)) == (lingua.annotator, lingua.detect(probe))
