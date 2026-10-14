"""tests/unit/e_cli/models/command: a path splits into the node it mounts under and its own name."""

from e_cli.models.command import CommandCard, CommandGroup


def test_command_card_splits_its_path() -> None:
    card = CommandCard(path="project env set", target="m:f", summary="s")
    assert (card.parent, card.name) == ("project env", "set")


def test_command_group_at_the_top_mounts_on_the_root() -> None:
    group = CommandGroup(path="auth", help="h")
    assert (group.parent, group.name) == ("", "auth")
