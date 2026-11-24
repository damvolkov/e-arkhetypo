r"""The templates a request may select — the allowlist, as data.

Kept free of service imports so the bank is testable on its own. Only these
import paths ever reach `run_pipeline`: a `template` form field is typed to this
enum, so it cannot name arbitrary code. A new document type is a new member and
a new file under `templates/`.
"""

from enum import StrEnum
from typing import Final


class Template(StrEnum):
    DOCUMENT = "templates.document.Document"
    PAPER = "templates.paper.Paper"


#: the templates that ship, in order; the bank and the mounted directory must agree.
SHIPPED: Final = [Template.DOCUMENT, Template.PAPER]
