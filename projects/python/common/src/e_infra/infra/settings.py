"""infra/settings: the dynamic composer — every ``*Settings`` of ``infra/config``, merged into one nested ``Settings``.

The config tree mirrors the module tree: ``infra/config/providers/drivers/database/psqlpy.py`` configures
``providers/drivers/database/psqlpy.py``, and its settings are read at ``st.providers.drivers.database.psqlpy`` — the
module path, the attribute chain and the module configured are one hierarchy. Scopes that serve no provider, engine or
processor sit at the top (``st.app.env``). Each scope keeps its own sources (``env_prefix``, ``env_file``,
``toml_file``, ``secrets_dir``), so adding a scope is just dropping a file in ``infra/config`` — ``base`` is the only
thing skipped. Consumers import the lazy singleton: ``from e_infra.infra.settings import settings as st`` →
``st.crypto.alg`` (env, secrets and config files are read on that first access, never at import)."""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

from e_infra.infra.config.base import BaseSettings, Secret
from e_infra.infra.proxy import LazyProxy
from e_infra.ops.file import FileFinder

__all__ = ["BaseSettings", "Secret", "Settings", "settings"]

type Paths = dict[tuple[str, ...], type[BaseSettings]]

_SETTINGS_RE = re.compile(r"^([A-Z]\w*)Settings$")
_CONFIG = f"{__package__}.config"
### derived from the package, never spelled: materialization rewrites imports, not strings (`e_infra.infra` → `infra`).
_SCOPES: Paths = {
    tuple(cls.__module__.removeprefix(f"{_CONFIG}.").split(".")): cls
    for cls in FileFinder(_CONFIG, skip=frozenset({"base"}), recursive=True)
    .discover(BaseSettings, pattern=_SETTINGS_RE)
    .values()
}


def _grow(name: str, scopes: Paths) -> type[BaseModel]:
    """The model of a branch: one field per first path segment, a scope itself where the path ends there."""
    heads = sorted({path[0] for path in scopes})
    below = {head: {path[1:]: cls for path, cls in scopes.items() if path[0] == head} for head in heads}
    fields: dict[str, Any] = {
        head: ((rest[()] if () in rest else _grow(f"{name}{head.title()}", rest)), ...) for head, rest in below.items()
    }
    return create_model(name, __config__=ConfigDict(frozen=True), **fields)


Settings: Any = _grow("Settings", _SCOPES)


def _build(model: type[BaseModel], overrides: dict[str, Any]) -> Any:
    """A branch built from its children, a scope from its own layers; an override dict reaches the scope it names."""
    return (
        model(**overrides)
        if issubclass(model, BaseSettings)
        else model(
            **{name: _build(field.annotation, overrides.get(name, {})) for name, field in model.model_fields.items()}
        )
    )


def _load(cls: Any, **overrides: Any) -> Any:
    """Build the composite: every scope reads its own layers; an override dict nested like the tree beats them."""
    return _build(cls, overrides)


### the parent constructor cannot honour per-scope sources or per-scope overrides: each scope loads itself.
Settings.load = classmethod(_load)
### no I/O at import: env, secrets and config files are read on the first attribute access, once per process.
settings: LazyProxy[Any] = LazyProxy(lambda: _load(Settings))
