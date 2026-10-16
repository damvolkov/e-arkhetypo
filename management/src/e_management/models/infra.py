"""models.infra: the DTOs of the CI library — the feature map and one project's defaults, validated at load.

The map (``infra/features.yml``) says which atomic job fragments a feature brings, which tokens its
fragments demand, what it requires to be selectable and what it replaces when it arrives. Defaults
(``systems/<s>/.github/ci.defaults.yml``) are a project's own truth: the features it ships and the
name-neutral configuration (matrix, markers, site) the fragments substitute. Everything else the
assembler derives from the target name — brand, package, smoke, allowlist are never stored twice."""

from msgspec import Struct

##### TYPES #####


class Feature(Struct, frozen=True, kw_only=True, omit_defaults=True):
    """One selectable slice of CI: its label for the wizard, the job fragments it brings per workflow,
    the files it copies, what must already be on, the gate that keeps it inert, and the tokens it needs."""

    label: str
    jobs: dict[str, tuple[str, ...]]
    gate: str | None = None
    vars: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    replaces: tuple[str, ...] = ()
    tag_trigger: bool = False
    files: tuple[str, ...] = ()
    setup: str = ""
    tokens: tuple[str, ...] = ()


class FeatureMap(Struct, frozen=True, kw_only=True):
    """The whole library: every feature, keyed by the name the map and the wizard use."""

    version: int
    features: dict[str, Feature]


class Defaults(Struct, frozen=True, kw_only=True, omit_defaults=True):
    """What a project ships by default: its features and the name-neutral tokens fragments demand."""

    features: tuple[str, ...] = ()
    tokens: dict[str, str] = {}
