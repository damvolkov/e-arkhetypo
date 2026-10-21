"""tests/unit: models.section — the closed taxonomy, in its fixed order."""

from e_graph.models.section import ORDER, PREFIXES, Section


def test_order_is_the_declared_law() -> None:
    assert [section.value for section in ORDER] == [
        "ingest",
        "normalize",
        "classify",
        "extract",
        "validate",
        "enrich",
        "inference",
        "audit",
        "transform",
        "report",
    ]
    assert Section.CUSTOM not in ORDER
    assert (*ORDER, Section.CUSTOM) == tuple(Section)


def test_prefixes_cover_every_section_once() -> None:
    assert set(PREFIXES) == set(Section)
    assert len(set(PREFIXES.values())) == len(PREFIXES)
    assert all(prefix.isupper() and len(prefix) == 3 for prefix in PREFIXES.values())
