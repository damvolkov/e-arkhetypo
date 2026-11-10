"""tests/unit/e_infra/infra/query: every bank member is a described statement, and its statement is its own."""

from typing import TYPE_CHECKING

import pytest

from e_infra.infra.auth.query import AuthQuery
from e_infra.infra.query import CacheQuery, DatabaseQuery, Query, QueueQuery

if TYPE_CHECKING:
    from collections.abc import Iterable

BANKS = (AuthQuery, CacheQuery, DatabaseQuery, QueueQuery)


@pytest.mark.parametrize("bank", BANKS, ids=[bank.__name__ for bank in BANKS])
async def test_query_bank_members_are_distinct_and_described(bank: Iterable[Query]) -> None:
    ### two equal tuples in one enum would alias silently: every declared name must be its own member.
    assert all(isinstance(member, Query) and member.sql.strip() and member.description for member in bank)


@pytest.mark.parametrize("bank", BANKS, ids=[bank.__name__ for bank in BANKS])
async def test_query_bank_statements_are_unique(bank: Iterable[Query]) -> None:
    members = list(bank)
    assert len({member.sql for member in members}) == len(members)
