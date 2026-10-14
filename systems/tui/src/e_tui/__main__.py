"""python -m e_tui — run the reference fake app over the standard architecture.

`etui` is one thin line over `e_tui.demo`: a wizard that picks options across a validated flow and emits an
`AppBlueprint`. The reusable example lives in `e_tui.demo` and `e_tui.pages`; copy those to start a host app."""

import sys
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from e_tui.demo import build

if TYPE_CHECKING:
    from collections.abc import Sequence


def _show_version() -> None:
    """Print the installed version, or the dev marker when running from a tree."""
    try:
        print(version("e-tui"))
    except PackageNotFoundError:
        print("0.0.0.dev")


def main(argv: Sequence[str] | None = None) -> None:
    """`--version` prints and exits; anything else runs the reference wizard."""
    match list(argv if argv is not None else sys.argv[1:]):
        case ["--version"]:
            _show_version()
        case _:
            build().run()


if __name__ == "__main__":
    main()
