r"""Cypher made safe for FalkorDB: no stray control byte survives to the server.

Two failure modes, both from a control byte landing inside a quoted property
value (PDF text with tables and symbols leaves them in names and summaries):

- FalkorDB reads a statement as a C string and cuts it at the first NUL, so a
  `\x00` in a name gives `Unterminated string` and the whole load 502s.
- `str.splitlines` treats more than `\n` as a line break — `\v \f \x1c-\x1e \x85
  \u2028 \u2029` too — so those bytes split a value in two *before* the exporter
  text is even assembled into statements.

The exporter already escapes `\`, quotes and `\n`/`\r`, and JSON values come out
of `json.dumps` with controls escaped, so what still needs handling is the
remaining C0 set (except tab/newline/CR, which are conventional whitespace a name
can hold), DEL and the extra line separators. Removing them before the text is
split closes both modes without altering ordinary text.
"""

import re
from typing import Final

##### CONSTANTS #####

# All C0 controls except HT/LF/CR (conventional whitespace a name can hold and
# which the exporter or the statement structure already owns), plus DEL, NEL and
# the Unicode line/paragraph separators. The extras beyond C0 are what
# str.splitlines treats as a break and would corrupt into a new statement.
CONTROL: Final = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x85\u2028\u2029]")

##### PUBLIC #####


def sanitize(text: str) -> str:
    """The Cypher text with every value-breaking control character removed."""
    return CONTROL.sub("", text)
