"""tests/unit: instrument.state — the RunState's fixed shape, its scoped context, the shared branches."""

import uuid

import pytest

from e_graph.instrument.state import Channels, InfraState, InstrumentState, ProvidersState, RunState
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.state import LogicState
from infra.state import State
from processors.doc import DocProcessor


def test_run_state_shape_fixed_at_birth(run_state: RunState) -> None:
    assert set(run_state) == {"id", "correlation", "pipeline", "infra", "logic", "instrument"}
    with pytest.raises(RuntimeError, match="Sealed"):
        run_state["infra"] = State()
    with pytest.raises(AttributeError, match="Sealed state has no node"):
        _ = run_state.typo


def test_run_state_context_zone_open(run_state: RunState) -> None:
    run_state.context.document.pages = 3
    assert run_state.context.document.pages == 3


def test_run_state_context_is_scoped_by_id(system: State) -> None:
    first, second = RunState(system), RunState(system)
    first.context.amount = "1"
    assert "amount" not in second.context
    assert system.instrument.contexts[first.id] is first.context


def test_run_state_id_uuid7_unless_named(system: State) -> None:
    assert uuid.UUID(RunState(system).id).version == 7
    assert RunState(system, run_id="fixed").id == "fixed"


def test_run_state_keeps_its_request_as_a_link(system: State) -> None:
    assert RunState(system).correlation == ""
    state = RunState(system, correlation="req-1")
    assert (state.correlation, state.id != "req-1") == ("req-1", True)


def test_run_state_id_live_twice_refused(system: State) -> None:
    RunState(system, run_id="twin")
    with pytest.raises(ValueError, match="already open"):
        RunState(system, run_id="twin")


def test_run_state_release_drops_its_context(system: State) -> None:
    state = RunState(system)
    state.release()
    state.release()
    assert state.id not in system.instrument.contexts


def test_run_state_branches_typed(run_state: RunState) -> None:
    infra = run_state.infra
    assert isinstance(infra, InfraState)
    assert isinstance(infra.providers, ProvidersState)
    assert isinstance(run_state.logic, LogicState)
    assert isinstance(run_state.logic.agent, AgnosticAgent)
    assert isinstance(run_state.instrument, InstrumentState)
    assert infra.providers.telemetry.spec.name == "otel"
    assert run_state.instrument.telemetry.provider is infra.providers.telemetry


def test_run_state_graphs_are_the_system_singletons(run_state: RunState, system: State) -> None:
    assert run_state.infra is system.infra
    assert set(run_state.infra.graphs) == {"probe"}


def test_channels_outputs_default_empty(run_state: RunState) -> None:
    assert Channels(run=run_state).outputs == []


def test_run_state_reads_documents_through_the_infra_processor(run_state: RunState) -> None:
    assert isinstance(run_state.infra.processors.doc, DocProcessor)
