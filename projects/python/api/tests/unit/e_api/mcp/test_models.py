"""tests/unit/e_api/mcp/models: what an agent sends each tool, decoded as the engine decodes it — a field left out stays
unset, `null` sets, a malformed field is refused."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import msgspec
import pytest

from e_api.engines.health import ProviderHealth
from e_api.mcp.models import NoArgs, Status, UserArgs, UserUpdateArgs

UID = "9d1a5b58-0e0e-4a5e-9a3f-000000000000"


async def test_no_args_takes_nothing() -> None:
    assert msgspec.json.decode(b"{}", type=NoArgs) == NoArgs()


async def test_user_args_names_the_user_by_uuid() -> None:
    assert msgspec.json.decode(f'{{"user_id": "{UID}"}}'.encode(), type=UserArgs).user_id == UUID(UID)
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(b'{"user_id": "nobody"}', type=UserArgs)


async def test_user_update_args_leaves_out_what_is_not_sent() -> None:
    args = msgspec.json.decode(f'{{"user_id": "{UID}", "quota": "1.50"}}'.encode(), type=UserUpdateArgs)
    assert (args.email, args.birth, args.quota) == (msgspec.UNSET, msgspec.UNSET, Decimal("1.50"))


async def test_user_update_args_null_birth_is_a_value() -> None:
    args = msgspec.json.decode(f'{{"user_id": "{UID}", "birth": null}}'.encode(), type=UserUpdateArgs)
    assert args.birth is None
    dated = msgspec.json.decode(f'{{"user_id": "{UID}", "birth": "1990-01-02"}}'.encode(), type=UserUpdateArgs)
    assert dated.birth == date(1990, 1, 2)


async def test_user_update_args_refuses_a_malformed_email() -> None:
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(f'{{"user_id": "{UID}", "email": "not-an-email"}}'.encode(), type=UserUpdateArgs)


async def test_status_round_trips_the_providers_verdicts() -> None:
    verdict = ProviderHealth(name="store", required=True, ok=True, latency=1.5)
    status = Status(ready=True, providers=[verdict])
    assert msgspec.json.decode(msgspec.json.encode(status), type=Status) == status
