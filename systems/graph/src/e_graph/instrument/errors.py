"""instrument.errors: what the instrument raises — a broken contract at load time, a failed node at run time.

Every violation is caught while the graph is declared, before compile and long before a run: a
graph that loads is a graph whose every node is `async def node_<name>(state: RunState) -> str | None`
living in `nodes/<category>/node.py`, and whose every router names the targets it can reach."""

from enum import StrEnum, auto

from e_graph.instrument.models import NodeOutput


class ContractRule(StrEnum):
    """Each law the declaration is checked against."""

    ASYNC = auto()
    NAME = auto()
    LOCATION = auto()
    SIGNATURE = auto()
    STATE = auto()
    RETURN = auto()
    ROUTE = auto()


class ContractError(TypeError):
    """A declared node or route broke `rule`; `subject` names the offending callable."""

    def __init__(self, rule: ContractRule, subject: str, detail: str) -> None:
        self.rule = rule
        self.subject = subject
        super().__init__(f"[{rule}] {subject}: {detail}")


class NodeError(RuntimeError):
    """A node answered FAILED: the graph raises it so LangGraph stops the run (or retries, per its policy).

    The node's own exception never crosses the boundary — it lives in the log with its traceback; what
    travels is the FAILED `NodeOutput`, whose `error` names the original type and message."""

    def __init__(self, output: NodeOutput) -> None:
        self.output = output
        super().__init__(output.error)
