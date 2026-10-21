"""e_tui.models.object: the declarative contract of interactive objects — data, never widgets.

A step of a flow graph answers one question: *what kind of interaction, over what options*. That answer
is a `Spec`: a frozen, tagged msgspec struct, discriminated in any config file by its `kind` field. The
five kinds are the ones the house apps need today — toggle (many on/off), choice (pick one), input (a
line of text), confirm (a fork with a consequence), report (a page to read, advance-only).

The structs here know nothing about Textual; `e_tui.interact` binds each kind to the widget that
realizes it, and the user's answer comes back as a `Commit` — the one typed value every object yields.
"""

import msgspec

##### VOCABULARY #####


class Field(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """One selectable row: a stable key, a label to show, and an optional second line."""

    key: str
    label: str
    detail: str = ""


class Commit(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """The user's answer: the keys chosen (or the text typed), and whether the step was accepted."""

    values: tuple[str, ...] = ()
    ok: bool = True


##### SPECS #####


class ToggleSpec(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True, tag="toggle", tag_field="kind"):
    """Many switches: `defaults` start on, `locked` cannot be turned off (the house 'required' rule)."""

    prompt: str = ""
    fields: tuple[Field, ...] = ()
    defaults: tuple[str, ...] = ()
    locked: tuple[str, ...] = ()


class ChoiceSpec(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True, tag="choice", tag_field="kind"):
    """Pick exactly one: nothing commits until a radio answers, `selected` pre-picks."""

    prompt: str = ""
    fields: tuple[Field, ...] = ()
    selected: str | None = None


class InputSpec(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True, tag="input", tag_field="kind"):
    """One line of text; empty never commits. `secret` masks it as a password."""

    prompt: str = ""
    placeholder: str = ""
    secret: bool = False


class ConfirmSpec(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True, tag="confirm", tag_field="kind"):
    """A fork with a consequence: yes advances, no commits `ok=False` and the walk stays put."""

    prompt: str = ""
    detail: str = ""


class ReportSpec(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True, tag="report", tag_field="kind"):
    """A page to read: static lines, it always and instantly commits."""

    prompt: str = ""
    lines: tuple[str, ...] = ()


Spec = ToggleSpec | ChoiceSpec | InputSpec | ConfirmSpec | ReportSpec
