"""models.project: the demo domain in the shapes its data takes — constrained input, stored record, owned state.

`ProjectSpec` is what a user may say about a new project: it crosses a trust boundary, so its constraints
(`Meta` pattern, length) run on `msgspec.convert` — once, at the edge — and the interior trusts the type.
`Project` is the document the store keeps. Constrained aliases (`ProjectName`, `EnvKey`) name a rule once
and reuse it wherever the value travels."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from msgspec import Meta, Struct, field

##### CONSTRAINED TYPES #####
### classic aliases, not PEP 695 `type`: msgspec reads the `Meta` of a plain `Annotated` at convert time.
ProjectName = Annotated[str, Meta(pattern=r"^[a-z][a-z0-9-]{1,38}$", description="lowercase slug, 2-39 chars")]
EnvKey = Annotated[str, Meta(pattern=r"^[A-Z_][A-Z0-9_]*$", description="UPPER_SNAKE variable name")]
Description = Annotated[str, Meta(max_length=120)]


##### ENUMS #####
class ProjectState(StrEnum):
    """Where a project is in its life: a draft until activated, archived instead of deleted when kept."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


##### TYPES #####
class ProjectSpec(Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Input: everything `project create` accepts, validated by `msgspec.convert` before the core sees it."""

    name: ProjectName
    description: Description = ""
    state: ProjectState = ProjectState.DRAFT


class Project(Struct, frozen=True, kw_only=True):
    """Record: one JSON document per project in the store — the spec, when it was born, its variables."""

    name: ProjectName
    description: Description = ""
    state: ProjectState = ProjectState.DRAFT
    created: datetime
    env: dict[EnvKey, str] = field(default_factory=dict)
