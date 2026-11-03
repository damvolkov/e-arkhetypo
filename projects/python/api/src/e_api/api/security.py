"""api.security: the OpenAPI contract of the key — who may call is `infra/auth`'s, one system for both doors.

A route declares its access in its options (`opt=OPT[Access.USER]`); the token middleware has resolved the caller from the
`Authorization` header before any route runs and the guard admits it (`infra/auth/guard`). This module only tells the
OpenAPI pages how a key is sent: a bearer, opaque — a key `POST /auth/accounts/{name}/token` hands out, not a JWT."""

from enum import StrEnum
from typing import Final

from litestar.openapi.spec import SecurityScheme


##### CONTRACT #####
class SecuritySchemeName(StrEnum):
    BEARER = "bearerAuth"


BEARER_SCHEME = SecurityScheme(type="http", scheme="bearer", bearer_format="opaque")
### OpenAPI requirement maps key by scheme id: the enum owns the vocabulary, `.value` is the str edge litestar types.
SECURITY: Final[list[dict[str, list[str]]]] = [{SecuritySchemeName.BEARER.value: []}]
