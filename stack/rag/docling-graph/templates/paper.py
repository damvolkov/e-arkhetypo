"""Template for a research paper: typed nodes that keep the graph small.

The default `Document` template lets the model enumerate every proper noun, so a
paper's 240-odd cited authors swamp the ~ten things worth knowing. This one
names only the paper's own authors, its central concepts, the datasets it uses
and the organizations that made it — authors and citations with no slot to land
in simply are not extracted.
"""

from typing import Any

from pydantic import BaseModel, Field


def edge(label: str, **kwargs: Any) -> Any:
    """A field that is a graph edge named `label`."""
    return Field(json_schema_extra={"edge_label": label}, **kwargs)


class Author(BaseModel):
    """One of this paper's own authors — not a person merely cited in it."""

    model_config = {"is_entity": True, "graph_id_fields": ["name"]}

    name: str = Field(description="Author name as written on the paper")
    affiliation: str = Field(description="The author's organization, if stated", default="")


class Concept(BaseModel):
    """A method, model or idea central to the paper."""

    model_config = {"is_entity": True, "graph_id_fields": ["name"]}

    name: str = Field(description="Name of the concept, e.g. 'dense retrieval'")
    definition: str = Field(description="One-sentence definition in the paper's terms", default="")


class Dataset(BaseModel):
    """A dataset, benchmark or corpus the paper uses or introduces."""

    model_config = {"is_entity": True, "graph_id_fields": ["name"]}

    name: str = Field(description="Dataset or benchmark name, e.g. 'Natural Questions'")


class Organization(BaseModel):
    """An organization that authored the work or published the venue."""

    model_config = {"is_entity": True, "graph_id_fields": ["name"]}

    name: str = Field(description="Organization name, e.g. 'IBM Research', 'FAIR'")


class Paper(BaseModel):
    """A research paper and the handful of entities that describe it."""

    model_config = {"is_entity": True, "graph_id_fields": ["title"]}

    title: str = Field(description="Paper title")
    abstract: str = Field(description="The paper's abstract, or a two-sentence summary")
    authors: list[Author] = edge("AUTHORED_BY", default_factory=list, description="The paper's own authors")
    concepts: list[Concept] = edge("ABOUT", default_factory=list, description="Central methods and ideas")
    datasets: list[Dataset] = edge("USES", default_factory=list, description="Datasets and benchmarks used")
    organizations: list[Organization] = edge("PUBLISHED_BY", default_factory=list, description="Organizations behind the work")
