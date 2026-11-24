"""Default template: a document, its summary and the entities it mentions.

docling-graph ships no `edge` import: a template declares the helper itself — the label rides in `json_schema_extra`.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def edge(label: str, **kwargs: Any) -> Any:
    """A field that is a graph edge named `label`."""
    return Field(json_schema_extra={"edge_label": label}, **kwargs)


class EntityKind(StrEnum):
    """The closed set of entity kinds a name may be."""

    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    PRODUCT = "product"
    CONCEPT = "concept"
    EVENT = "event"


class Entity(BaseModel):
    """A person, organization, place, product or concept named in the document."""

    model_config = {"is_entity": True, "graph_id_fields": ["name"]}

    name: str = Field(description="Entity name as written in the document")
    kind: EntityKind = Field(description="What kind of thing this entity is")


class Document(BaseModel):
    """The document as a whole."""

    model_config = {"is_entity": True, "graph_id_fields": ["title"]}

    title: str = Field(description="Document title")
    summary: str = Field(description="Two-sentence summary")
    entities: list[Entity] = edge("MENTIONS", default_factory=list, description="Entities named in the document")
