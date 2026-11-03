"""tests/unit/e_api/api/security: the OpenAPI contract of the key — a bearer, opaque, named once and referenced by every
guarded route."""

from typing import TYPE_CHECKING

from e_api.api.security import BEARER_SCHEME, SECURITY, SecuritySchemeName

if TYPE_CHECKING:
    from litestar.testing import TestClient


async def test_security_scheme_is_an_opaque_bearer() -> None:
    assert (BEARER_SCHEME.type, BEARER_SCHEME.scheme, BEARER_SCHEME.bearer_format) == ("http", "bearer", "opaque")


async def test_security_requirement_names_the_scheme_by_its_enum_value() -> None:
    assert [{SecuritySchemeName.BEARER.value: []}] == SECURITY
    assert SecuritySchemeName.BEARER.value == "bearerAuth"


def test_security_schema_publishes_the_scheme_and_guards_the_user_routes(client: TestClient) -> None:
    schema = client.get("/schema/openapi.json").json()
    assert schema["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
    assert schema["paths"]["/users"]["get"]["security"] == [{"bearerAuth": []}]
    assert "security" not in schema["paths"]["/health"]["get"]
