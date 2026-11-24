"""Regression: a stray control byte inside a value must never reach FalkorDB.

FalkorDB cuts a statement at a NUL (502 `Unterminated string`), and `str.splitlines`
turns other control bytes into false line breaks before the statements are even
assembled. `sanitize` runs on the exported text first, so both are closed here.
"""

import pytest

from sanitize import sanitize

##### DROPPED #####

# Every C0 control except HT/LF/CR, plus DEL and the extra line separators.
DROPPED = [
    ("\x00", "nul"),
    ("\x01", "soh"),
    ("\x08", "bs"),
    ("\x0b", "vtab"),
    ("\x0c", "ff"),
    ("\x1c", "fs"),
    ("\x1b", "esc"),
    ("\x1f", "us"),
    ("\x7f", "del"),
    ("\x85", "nel"),
    ("\u2028", "ls"),
    ("\u2029", "ps"),
]


@pytest.mark.parametrize("char,label", DROPPED, ids=[label for _, label in DROPPED])
def test_sanitize_drops_control(char: str, label: str) -> None:
    assert sanitize(f'MERGE (n {{id: "d"}})\nSET n.name = "Doc{char}ling";') == 'MERGE (n {id: "d"})\nSET n.name = "Docling";'


def test_sanitize_keeps_whitespace_and_text() -> None:
    """HT, LF, CR are conventional and structural; ordinary punctuation is kept."""
    text = 'MERGE (n {id: "d"})\nSET n.name = "Doc\tl\ning\rling (x86) — ok";'
    assert sanitize(text) == text


def test_sanitize_splitlines_no_false_break() -> None:
    """After sanitize the text splits only where the exporter put a real break."""
    text = 'SET n.name = "Doc\x0bling";\nCREATE (m {x: 1});'
    assert sanitize(text).splitlines() == ['SET n.name = "Docling";', "CREATE (m {x: 1});"]
