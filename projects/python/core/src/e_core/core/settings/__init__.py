"""core/settings: the dynamic composer — every ``*Settings`` in this package, merged into one ``Settings``.

Each subsystem keeps its own sources (``env_prefix``, ``env_file``, ``toml_file``, ``secrets_dir``), so
adding a scope is just dropping a file here — ``__init__`` and ``base`` are the only things skipped.
Consumers import the lazy singleton: ``from e_core.core.settings import settings as st`` → ``st.crypto.alg``
(env, secrets and config files are read on that first access, never at import)."""

import re
from typing import Any

from pydantic import ConfigDict, create_model

from e_core.core.proxy import LazyProxy
from e_core.core.settings.base import BaseSettings, Secret
from e_core.ops.file import FileFinder

__all__ = ["BaseSettings", "Secret", "Settings", "settings"]

_SETTINGS_RE = re.compile(r"^([A-Z]\w*)Settings$")
_SCOPES: dict[str, type[BaseSettings]] = {
    name.removesuffix("Settings").lower(): cls
    for name, cls in FileFinder(__name__, skip=frozenset({"base"})).discover(BaseSettings, pattern=_SETTINGS_RE).items()
}

_FIELDS: dict[str, Any] = {scope: (cls, ...) for scope, cls in _SCOPES.items()}
Settings: Any = create_model("Settings", __config__=ConfigDict(frozen=True), **_FIELDS)


def _load(cls: Any, **scopes: Any) -> Any:
    """Build the composite: every subsystem reads its own layers; a per-scope dict overrides them."""
    parts = {scope: klass(**scopes.pop(scope, {})) for scope, klass in _SCOPES.items()}
    return cls(**parts, **scopes)


### the parent constructor cannot honour per-scope sources or per-scope overrides: each scope loads itself.
Settings.load = classmethod(_load)
### no I/O at import: env, secrets and config files are read on the first attribute access, once per process.
settings: LazyProxy[Any] = LazyProxy(lambda: _load(Settings))
