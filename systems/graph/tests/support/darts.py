"""tests/support/darts: a section to run — specs and runners written to disk, the orchestrator over them, a scripted agent.

`DartsHarness` writes specs (built in code, so validated at birth) and runner modules (hook bodies given
as code) through the `SpecCrafter`, runs a section with a real `OrchestratorCore` and a real telemetry
edge, and answers every agent call with `ScriptedAgent` (or the real agent it is handed): each fused call is recorded (its specs, tier,
prompt) and answered per spec — `{}` by default, a scripted answer, or a provider failure.
`diagram` writes the section drawn at the top of `logic/orchestrator/core.py`."""

import textwrap
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final

from core.settings.darts import DartsSettings
from core.state import State
from e_graph.instrument.state import ContextState, InfraState, RunState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.errors import ProviderError
from e_graph.logic.models import (
    SIGNATURES,
    DeterministicSpec,
    Hook,
    JsonSchema,
    Provider,
    Reply,
    SemanticSpec,
    Usage,
)
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.models.section import Section

if TYPE_CHECKING:
    from adapters.otel import OtelAdapter
    from e_graph.logic.models import SectionRun
    from support.crafter import SpecCrafter

SECTION: Final[Section] = Section.EXTRACT
USAGE: Final[Usage] = Usage(input_tokens=10, output_tokens=5, total_tokens=15, calls=1)
OBJECT: Final[dict[str, Any]] = {"type": "object"}


class ScriptedAgent:
    """The agent as the orchestrator sees it: every call kept; each spec answered `{}`, or as scripted."""

    name: ClassVar[str] = "agent"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answers: dict[str, Any] = {}
        self.down: set[str] = set()

    async def run(
        self, instructions: str, prompt: str, output: Any, *, endpoint: Any = None, **_: Any
    ) -> Reply[dict[str, Any]]:
        names = tuple(output["required"])
        self.calls.append(
            {"specs": names, "tier": endpoint, "prompt": prompt, "instructions": instructions, "schema": output}
        )
        match sorted(self.down & set(names)):
            case []:
                answer = {name: self.answers.get(name, {}) for name in names}
                return Reply(
                    output=answer, provider=Provider.VLLM, model="scripted", usage=USAGE, latency_ms=1.0, attempts=1
                )
            case broken:
                msg = f"provider down for {broken}"
                raise ProviderError(msg)


class DartsHarness:
    """One pipeline (`doc`) under a crafter's root: write specs and runners, run a section, read the result."""

    def __init__(self, crafter: SpecCrafter, telemetry: OtelAdapter, agent: Any = None, **conf: Any) -> None:
        self.crafter, self.agent = crafter, ScriptedAgent() if agent is None else agent
        self._telemetry = InstrumentTelemetry(telemetry)
        self.orchestrator = self.configure(**conf)

    def configure(self, **conf: Any) -> OrchestratorCore:
        """A fresh orchestrator over the crafter's tree, DARTS settings as given."""
        self.orchestrator = OrchestratorCore(
            DartsSettings(**conf), specs=self.crafter.specs, runners=self.crafter.runners
        )
        return self.orchestrator

    ##### WRITING #####

    def deterministic(self, name: str, output: dict[str, Any] = OBJECT, **fields: Any) -> None:
        spec = DeterministicSpec(name=name, description=f"{name}.", output=JsonSchema(output), **fields)
        self.crafter.write_spec(SECTION, spec)

    def semantic(self, name: str, output: dict[str, Any] = OBJECT, **fields: Any) -> None:
        values: dict[str, Any] = {"instructions": f"Answer {name}.", **fields}
        spec = SemanticSpec(name=name, description=f"{name}.", output=JsonSchema(output), **values)
        self.crafter.write_spec(SECTION, spec)

    def runner(self, name: str, imports: str = "", **bodies: str) -> None:
        """A runner module whose hooks run the given bodies (`run="return {}"`), each with its docstring;
        `imports` (one statement per line) open the module."""
        functions = [
            f'{SIGNATURES[Hook(hook)]}:\n    """{hook} of {name}."""\n{textwrap.indent(body, "    ")}\n'
            for hook, body in bodies.items()
        ]
        lines = "".join(f"{line}\n" for line in imports.splitlines())
        self.crafter.write_runner(SECTION, name, (), functions="\n\n".join(functions), imports=lines)

    def diagram(self) -> None:
        """The section drawn at the top of core.py: four inputs, two semantic aggregates, an audit and its fallback."""
        self.deterministic("EXT-lines")
        self.runner("EXT-lines", run="return {}")
        self.deterministic("EXT-meta")
        self.runner("EXT-meta", run="return {}")
        self.semantic("EXT-kind")
        self.semantic("EXT-party")
        self.semantic("EXT-total", depends=("EXT-lines", "EXT-meta", "EXT-kind"))
        self.semantic("EXT-currency", depends=("EXT-party",))
        self.deterministic("EXT-audit", depends=("EXT-total", "EXT-currency"), fallback="EXT-recount")
        self.runner("EXT-audit", run="return {}")
        self.deterministic("EXT-recount")
        self.runner("EXT-recount", run="return {}")

    ##### RUNNING #####

    def state(self, pipeline: str = "doc") -> RunState:
        """A fresh run state over a system whose infra holds the scripted agent and this orchestrator."""
        infra = InfraState(
            adapters=None,  # ty: ignore[invalid-argument-type]
            processors=None,  # ty: ignore[invalid-argument-type]
            agent=self.agent,  # ty: ignore[invalid-argument-type]
            orchestrator=self.orchestrator,
            telemetry=self._telemetry,
            graphs=MappingProxyType({}),
        )
        system = State(infra=infra, contexts=ContextState())
        system.seal()
        return RunState(system, pipeline=pipeline)

    async def run(self, section: Section = SECTION) -> tuple[SectionRun, RunState]:
        """Run a section on a fresh state; the result and the state its outputs were written to."""
        state = self.state()
        return await self.orchestrator.run(section, state), state

    @staticmethod
    def written(state: RunState, section: Section = SECTION) -> dict[str, Any]:
        """Every output the run wrote under the section."""
        return dict(getattr(state.context, section))
