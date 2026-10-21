"""logic.orchestrator.fusion: many semantic specs, one agent call — fused instructions, prompt and schema; the reply split back.

Pure: no state, no I/O. Specs of one step and one tier are answered together, each under its own name:
the instructions are one brief per spec (description, instructions, example answers, the wiki pages it
names), the prompt carries each spec's material (what its `pre_run` prepared; identical material is
sent once, for every spec that shares it), and the schema is one object with one property per spec,
each that spec's own `output`. The agent validates the fused reply against it, retrying with the error;
`split` hands each spec its part. A group heavier than the budget is packed into several calls."""

import math
from functools import reduce
from itertools import groupby
from typing import TYPE_CHECKING, Any, Final

import msgspec

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from e_graph.logic.models import SpecNode

### characters per token, the usual estimate for English prose and JSON: a budget, not a count.
TOKEN_CHARS: Final[int] = 4
PREAMBLE: Final[str] = (
    "You answer several specifications at once. Each one is introduced below by its name as a heading, "
    "with what it asks. Reply with one JSON object holding one key per specification name; each value is "
    "that specification's answer, shaped exactly as its schema says. Answer from the material given."
)
BARE: Final[str] = "No material is given: answer from the instructions alone."


class SpecFusion:
    """The fusion of semantic specs into one call, and the split of its reply."""

    ##### PRIVATE #####

    @staticmethod
    def _pack_place(
        bins: tuple[tuple[tuple[str, ...], int], ...], item: tuple[str, int], budget: int, most: int
    ) -> tuple[tuple[tuple[str, ...], int], ...]:
        """First fit: the item joins the first bin it fits in, else opens its own."""
        name, weight = item
        fit = next(
            (index for index, (names, load) in enumerate(bins) if load + weight <= budget and len(names) < most), None
        )
        match fit:
            case None:
                return (*bins, ((name,), weight))
            case index:
                names, load = bins[index]
                return (*bins[:index], ((*names, name), load + weight), *bins[index + 1 :])

    ############################################################

    ##### PUBLIC #####

    @staticmethod
    def tokens(text: str) -> int:
        """Estimated tokens of a text."""
        return math.ceil(len(text) / TOKEN_CHARS)

    @staticmethod
    def brief(node: SpecNode, wiki: Mapping[str, str]) -> str:
        """One spec's part of the instructions: its name as heading, what it asks, its examples, its glossary."""
        spec: Any = node.spec
        examples = [f"Example answer: {msgspec.json.encode(example).decode()}" for example in spec.examples]
        glossary = [f"Glossary, {term}:\n{wiki[term].strip()}" for term in spec.wiki if term in wiki]
        return "\n".join([f"### {spec.name}", spec.description, spec.instructions, *examples, *glossary])

    @classmethod
    def weight(cls, node: SpecNode, wiki: Mapping[str, str], material: str = "") -> int:
        """The tokens a spec adds to a call: its brief, its schema, its material."""
        schema = msgspec.json.encode(dict(node.spec.output)).decode()
        return cls.tokens(cls.brief(node, wiki)) + cls.tokens(schema) + cls.tokens(material)

    @classmethod
    def pack(cls, weights: Mapping[str, int], budget: int, most: int) -> list[tuple[str, ...]]:
        """Specs into calls, first-fit decreasing: each call within `budget` tokens and `most` specs; a spec
        heavier than the budget gets a call of its own. Deterministic: ties break by name, names sorted."""
        ordered = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
        bins = reduce(lambda acc, item: cls._pack_place(acc, item, budget, most), ordered, ())
        return [tuple(sorted(names)) for names, _ in bins]

    @classmethod
    def instructions(cls, nodes: Sequence[SpecNode], wiki: Mapping[str, str]) -> str:
        """The fused instructions: the preamble, then one brief per spec."""
        return "\n\n".join([PREAMBLE, *(cls.brief(node, wiki) for node in nodes)])

    @staticmethod
    def prompt(material: Mapping[str, str]) -> str:
        """Each spec's material under its name; specs sharing the same material get it once, together."""
        shared = groupby(
            sorted((text, name) for name, text in material.items() if text.strip()), key=lambda pair: pair[0]
        )
        parts = [f"### Material for {', '.join(name for _, name in group)}\n{text}" for text, group in shared]
        return "\n\n".join(parts) or BARE

    @staticmethod
    def schema(nodes: Sequence[SpecNode]) -> dict[str, Any]:
        """One object, one required property per spec, each that spec's own output schema; nothing else allowed."""
        return {
            "type": "object",
            "title": "fused",
            "properties": {node.spec.name: dict(node.spec.output) for node in nodes},
            "required": [node.spec.name for node in nodes],
            "additionalProperties": False,
        }

    @staticmethod
    def split(reply: Mapping[str, Any], names: Sequence[str]) -> dict[str, Any]:
        """Each spec's part of a fused reply, by name."""
        return {name: reply[name] for name in names}
