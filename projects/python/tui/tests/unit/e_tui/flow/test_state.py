"""tests/unit/e_tui/flow/state: the shared bag — entry, answers, and the non-mutating shadow-path helpers."""

from e_tui.flow.graph import Graph
from e_tui.flow.page import Page
from e_tui.flow.state import FlowState, has, seed
from e_tui.models.object import ConfirmSpec
from infra.state import State


def _flow() -> Graph:
    return Graph("g", (Page("a", "A", ConfirmSpec()), Page("b", "B", ConfirmSpec())))


def test_state_opens_at_the_entry_page() -> None:
    state = FlowState(_flow())
    assert state.at == "a"
    assert state.here.id == "a"


def test_state_keeps_a_given_position_when_rebuilt() -> None:
    assert FlowState(_flow(), at="b", trail=("a",)).here.id == "b"


def test_state_starts_with_an_empty_trail() -> None:
    assert FlowState(_flow()).trail == ()


def test_state_answers_namespace_is_created_empty_on_first_touch() -> None:
    assert dict(FlowState(_flow()).answers) == {}


def test_state_reads_back_a_committed_answer() -> None:
    state = FlowState(_flow())
    state.answers["a"] = ("x", "y")
    assert state.values_for("a") == ("x", "y")


def test_state_reads_uncommitted_answers_as_empty() -> None:
    assert FlowState(_flow()).values_for("never") == ()


##### PATHS #####


def test_has_is_false_on_a_missing_path() -> None:
    assert has(State(), "system") is False


def test_has_is_true_once_a_top_level_path_is_seeded() -> None:
    bag = State()
    seed(bag, "system", object())
    assert has(bag, "system") is True


def test_seed_grows_a_branch_for_a_dotted_path() -> None:
    bag = State()
    seed(bag, "system.template", object())
    assert has(bag, "system")
    assert has(bag, "system.template")


def test_seed_reuses_an_existing_branch_for_a_sibling() -> None:
    bag = State()
    seed(bag, "system.template", object())
    seed(bag, "system.name", object())
    assert has(bag, "system.template")
    assert has(bag, "system.name")


def test_has_a_value_that_is_not_a_branch_hides_deeper_paths() -> None:
    bag = State()
    seed(bag, "system", object())  # a leaf, not a branch
    assert has(bag, "system") is True
    assert has(bag, "system.template") is False


def test_seed_does_not_read_through_auto_vivification() -> None:
    bag = State()
    assert has(bag, "system") is False
    assert "system" not in bag  # the presence test never grew a node
