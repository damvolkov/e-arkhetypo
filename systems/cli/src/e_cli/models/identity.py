"""models.identity: who a run acts as — the credential and where it came from, never printed in clear."""

from dataclasses import dataclass, field
from enum import StrEnum

##### DEFAULTS #####
REDACTION: str = "**********"
VISIBLE: int = 4  # trailing characters a masked token keeps, enough to tell two logins apart


##### ENUMS #####
class IdentityOrigin(StrEnum):
    """Where the credential was found, in resolution order: the flag beats the env, the env beats the store."""

    FLAG = "flag"
    ENV = "env"
    STORE = "store"


##### TYPES #####
@dataclass(frozen=True, slots=True)
class Identity:
    """The authenticated caller of one run — interior, code-owned, so pure Python; the token stays out of `repr`."""

    origin: IdentityOrigin
    token: str = field(repr=False)

    @property
    def masked(self) -> str:
        return f"{REDACTION}{self.token[-VISIBLE:]}"
