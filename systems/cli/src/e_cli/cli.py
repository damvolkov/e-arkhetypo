"""e-cli entrypoint: `ecli` — the command tree is two tables, and nothing under commands/ loads until it runs.

`GROUPS` and `CARDS` are the whole surface. `build` is the composition root: it turns the tables into
cyclopts apps and mounts every card by its `module:function` string, so importing this module imports no
command, and `ecli --help` or any group listing is served from the cards alone. The meta app runs the
`Launcher` first on every call: global options, the run's lifespan, injection by type, the error boundary.

Adding a command is one row in `CARDS` plus one plain function; a command that needs a new group adds a
row in `GROUPS`, parents before children. `tests/unit/e_cli/test_cli.py` resolves every target, so a
typo fails the gate, never a user.

    ecli auth     login · status · logout
    ecli project  list · create · remove
    ecli project env   set · list
    ecli history  list · undo
"""

import sys
from importlib.metadata import version

from cyclopts import App

from e_cli.models.command import CommandCard, CommandGroup
from e_cli.runtime.launcher import Launcher

##### TREE #####
GROUPS: tuple[CommandGroup, ...] = (
    CommandGroup(path="auth", help="The credential the cli acts with: store, inspect, drop."),
    CommandGroup(path="project", help="Projects of the demo domain."),
    CommandGroup(path="project env", help="Environment variables of one project."),
    CommandGroup(path="history", help="Every run that wrote to the store, and the undo of the last one."),
)

CARDS: tuple[CommandCard, ...] = (
    CommandCard(path="auth login", target="e_cli.commands.auth:login", summary="Store a credential for later runs."),
    CommandCard(path="auth status", target="e_cli.commands.auth:status", summary="Show who this run acts as."),
    CommandCard(path="auth logout", target="e_cli.commands.auth:logout", summary="Drop the stored credential."),
    CommandCard(path="project list", target="e_cli.commands.project:listing", summary="Every project."),
    CommandCard(path="project create", target="e_cli.commands.project:create", summary="Create an empty project."),
    CommandCard(path="project remove", target="e_cli.commands.project:remove", summary="Delete a project."),
    CommandCard(path="project env set", target="e_cli.commands.project:env_set", summary="Set one variable."),
    CommandCard(path="project env list", target="e_cli.commands.project:env_list", summary="Every variable."),
    CommandCard(path="history list", target="e_cli.commands.history:listing", summary="Every recorded run."),
    CommandCard(path="history undo", target="e_cli.commands.history:undo", summary="Revert the last recorded run."),
)


def build() -> App:
    """Composition root: the tree from the tables, the launcher on the meta app. Imports no command module."""
    root = App(name="ecli", help="e-stack cli template.", version=version("e-cli"), result_action="return_value")
    apps = {"": root}
    for group in GROUPS:
        apps[group.path] = App(name=group.name, help=group.help)
        apps[group.parent].command(apps[group.path])
    for card in CARDS:
        apps[card.parent].command(card.target, name=card.name, help=card.summary)
    root.meta.default(Launcher(root, CARDS).run)
    return root


def main() -> None:
    """The `ecli` script: build, run, exit with the launcher's code."""
    sys.exit(build().meta(sys.argv[1:]))
