"""core.session: the serializable shadow of the walk — what the draft stores and what a restart re-seeds.

The live truth is ``FlowState`` (cursor, trail, per-page answers); this is the snapshot: enough to
rebuild the same graph and place the cursor back on the same page with the same answers. Every
decision the wizard takes lands here at ``<section>.<key>`` names, the same the hooks write."""

from msgspec import Struct

##### TYPES #####


class Session(Struct, kw_only=True):
    """Every decision taken so far — plain values, msgspec-round-trip, the draft's whole payload."""

    template: str = ""
    name: str = ""
    off: tuple[str, ...] = ()
    drop: tuple[str, ...] = ()
    ci_off: tuple[str, ...] = ()
    dest: str = ""
    at: str = ""
    trail: tuple[str, ...] = ()
    answers: dict[str, tuple[str, ...]] = {}
    verify_tests: bool = True

    @property
    def ready(self) -> bool:
        """Enough is decided to build the project: the name and where it goes."""
        return bool(self.template and self.name and self.dest)
