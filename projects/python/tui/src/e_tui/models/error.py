"""e_tui.models.error: typed failures of the template — a bad spec, flow or interaction dies early."""

##### ROOT #####


class TuiError(Exception):
    """All e-tui exceptions inherit from this root."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


##### SPEC #####


class SpecError(TuiError):
    """A layout spec that violates the geometry, depth or identity law of `e_tui.layout.spec`."""


##### FLOW #####


class FlowError(TuiError):
    """A flow graph that cannot run: empty, repeated page ids, or a walk onto an unknown page."""


##### STRUCTURE #####


class PageStructureError(TuiError):
    """A page added to the flow out of turn: a repeated id, or a dependency its predecessors never produce."""


##### INTERACTION #####


class InteractError(TuiError):
    """An interactive object cannot be built or bound: unknown kind, or a widget/spec mismatch."""
