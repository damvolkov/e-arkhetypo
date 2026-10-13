"""core/struct: msgspec models validated however they are born — decoded at the edge or built in code.

msgspec validates only while decoding (`decode`, `convert`): a `Struct(...)` built in code skips every
constraint — `Meta` patterns, bounds, custom types. `CheckedStruct` closes that gap with one path,
msgspec's own: a struct built outside a decode re-validates itself by converting its builtin form back
into its type, so every constraint, nested field and error location (`- at $.output`) is msgspec's,
never a hand-written duplicate — and the instance then holds the checked values, exactly as if decoded.
Cross-field rules go in `_check`, which runs once per instance.

A complex type is a **checked type**: a subclass of a builtin (`dict`, `list`, `tuple`, `str`, `int`,
`float`) that validates in its constructor and raises `ValueError` — with any third-party library it
needs, and any derived state (a compiled validator) cached on itself. It decodes through
`CheckedStruct.dec_hook` — built from its decoded form, so validated — and encodes through
`CheckedStruct.enc_hook` back to that builtin (msgspec encodes `dict`/`list`/`tuple` subclasses alone,
never `str`/`int`/`float` ones). A type msgspec does not know and that is no builtin subclass stays refused.

Decoding is trusted: inside `CheckedStruct.trusted()` the instance skips the round trip (msgspec just
validated it); `CheckedStruct.convert` is that decode for values already parsed, hook and trust included. Forgetting the block costs one redundant validation, never a missed one."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Final, overload

import msgspec
from msgspec.structs import force_setattr

if TYPE_CHECKING:
    from collections.abc import Iterator

### the builtins a checked type may extend: msgspec encodes them natively, and builds them from their decoded form.
BUILTINS: Final[tuple[type, ...]] = (dict, list, tuple, str, int, float)
TRUSTED: Final[ContextVar[bool]] = ContextVar("struct_trusted", default=False)


class CheckedStruct(msgspec.Struct, frozen=True):
    """Base of an immutable model that is never invalid: validated on decode by msgspec, on construction by itself."""

    def __post_init__(self) -> None:
        match TRUSTED.get():
            case True:
                self._check()
            case _:
                ### the rebuilt twin runs `_check` itself; this instance adopts its checked values, field by field.
                with self.trusted():
                    builtins = msgspec.to_builtins(self, enc_hook=self.enc_hook)
                    twin = msgspec.convert(builtins, type(self), dec_hook=self.dec_hook)
                _ = [force_setattr(self, name, getattr(twin, name)) for name in self.__struct_fields__]

    def _check(self) -> None:
        """Cross-field rules, raising `ValueError`; a single field's rule belongs to its type."""

    ############################################################

    @staticmethod
    def dec_hook(kind: type, value: Any) -> Any:
        """Decode a checked type: built — and so validated — from its decoded form."""
        match kind:
            case type() if issubclass(kind, BUILTINS):
                return kind(value)
            case _:
                msg = f"{kind!r} is no checked type: subclass a builtin and validate in the constructor"
                raise TypeError(msg)

    @staticmethod
    def enc_hook(value: Any) -> Any:
        """Encode a checked type as the builtin it extends."""
        match [base for base in type(value).__mro__ if base in BUILTINS]:
            case [builtin, *_]:
                return builtin(value)
            case _:
                msg = f"{type(value)!r} is no checked type: subclass a builtin and validate in the constructor"
                raise TypeError(msg)

    @overload
    @classmethod
    def convert[T](cls, value: Any, kind: type[T]) -> T: ...

    @overload
    @classmethod
    def convert(cls, value: Any, kind: Any) -> Any: ...

    @classmethod
    def convert(cls, value: Any, kind: Any) -> Any:
        """Decode builtins (a parsed dict, a row) into a checked model — or a union of them, as msgspec types it:
        the hook passed, the decode trusted."""
        with cls.trusted():
            return msgspec.convert(value, kind, dec_hook=cls.dec_hook)

    @staticmethod
    @contextmanager
    def trusted() -> Iterator[None]:
        """Mark a decode: the structs msgspec builds inside were just validated, and skip the round trip."""
        token = TRUSTED.set(True)
        try:
            yield
        finally:
            TRUSTED.reset(token)
