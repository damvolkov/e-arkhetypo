"""tests/unit/e_cli/models/project: the spec is a closed contract — strays are refused at convert time."""

import msgspec
import pytest

from e_cli.models.project import ProjectSpec, ProjectState


def test_project_spec_forbids_unknown_fields() -> None:
    with pytest.raises(msgspec.ValidationError, match="unknown field"):
        msgspec.convert({"name": "demo", "owner": "x"}, ProjectSpec)


def test_project_spec_defaults_to_a_draft() -> None:
    assert msgspec.convert({"name": "demo"}, ProjectSpec).state is ProjectState.DRAFT
