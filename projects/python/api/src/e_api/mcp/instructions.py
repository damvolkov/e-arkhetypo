"""e_api.mcp.instructions: what the server tells a client about itself — the door's own words."""

from typing import Final

INSTRUCTIONS: Final[str] = (
    "e-api's MCP door: the tools are the REST API's routes, served to an agent under the same keys and the same "
    "refusals. Send your key as `Authorization: Bearer <key>`. api_health and api_status say whether the service is up "
    "and which of its providers answer — any caller may ask. api_user_list and api_user_read read the user records "
    "and need an account's key; api_user_create, api_user_update and api_user_delete write them and need the "
    "admin's. A refusal is the API's own words: no key, or a key short of the tool's access."
)
