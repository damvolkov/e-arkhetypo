"""The template bank is the allowlist and stays true to the mounted directory."""

from pathlib import Path

import pytest

from template import SHIPPED, Template

TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "stack" / "rag" / "docling-graph" / "templates"


def test_template_is_a_closed_enum() -> None:
    assert [t.value for t in Template] == ["templates.document.Document", "templates.paper.Paper"]


@pytest.mark.parametrize("template", SHIPPED, ids=[t.name for t in SHIPPED])
def test_bank_entry_has_a_module(template: Template) -> None:
    """Each bank path's module exists under the mounted templates directory."""
    module = template.value.split(".")[1]  # templates.<module>.<Class>
    assert (TEMPLATES_DIR / f"{module}.py").is_file(), template.value


def test_every_shipped_template_file_is_banked() -> None:
    """A template file added to the directory without a bank entry is caught here."""
    banked = {t.value.split(".")[1] for t in SHIPPED}
    files = {p.stem for p in TEMPLATES_DIR.glob("[!_]*.py")}
    assert files == banked, (files, banked)
