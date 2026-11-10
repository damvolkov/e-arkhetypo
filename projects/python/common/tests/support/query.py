"""tests/support/query: a statement a test writes inline, as the `Query` the database port takes."""

from typing import LiteralString, cast

from e_infra.infra.query import Query


def sql(text: str) -> Query:
    """`text` as a `Query` — a test's own statement, some built around a name, is no member of any consumer's bank."""
    ### the one cast of the tests: a statement here is data, as it is where PgQueuer hands one over.
    return Query(cast("LiteralString", text), "A statement of a test.")  # ast-grep-ignore: cast
