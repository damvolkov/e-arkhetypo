"""infra/logger: structured JSON in prod, ordered plain text in dev/local.

Nothing loads at import: `setup` and the `logger` singleton run on first use, exactly once per process."""

import logging
import sys
from collections.abc import Callable, Sequence  # noqa: TC003 — beartype resolves ELogger's annotations at runtime
from typing import Any, ClassVar, Protocol, TextIO, runtime_checkable

import beartype
import msgspec
import structlog
from structlog.typing import (  # noqa: TC002 — beartype resolves ELogger's annotations at runtime
    BindableLogger,
    EventDict,
    Processor,
    WrappedLogger,
)

from e_infra.infra.config.app import Env
from e_infra.infra.proxy import LazyProxy
from e_infra.infra.settings import settings as st


##### TYPES #####
@runtime_checkable
class TextSink(Protocol):
    """What ELogger genuinely consumes from a stream: the tty probe at construction. Nothing else."""

    def isatty(self) -> bool: ...


##### DEFAULTS #####
DEFAULT_ENV: Env = Env.DEV
DEFAULT_LEVEL: int = logging.INFO
DEFAULT_ORDER: Sequence[str] = ()
DEFAULT_SEP: str = " || "
DEFAULT_HEAD_SEP: str = " | "
DEFAULT_KV_FMT: str = "{key}: {value}"
DEFAULT_LEVEL_WIDTH: int = 8
DEFAULT_STREAM: TextIO = sys.stdout

##### EVENT DICT KEYS (SET BY STRUCTLOG PROCESSORS) #####
TIMESTAMP_KEY = "timestamp"
LEVEL_KEY = "level"
EVENT_KEY = "event"
EXCEPTION_KEY = "exception"

##### ANSI #####
RESET = "\033[0m"
DIM = "\033[2m"
LEVEL_COLORS: dict[str, str] = {
    "debug": "\033[36m",
    "info": "\033[32m",
    "warning": "\033[33m",
    "error": "\033[31m",
    "critical": "\033[1;31m",
}


##### RENDERER #####
class ELogger:
    """Render `timestamp | LEVEL | event || key: value || ...`, priority keys first, rest sorted.

    Also the setup surface: `ELogger.setup` configures structlog and marks the process configured,
    `ELogger.load` is what the lazy `logger` singleton builds — setup on first use, never at import."""

    __slots__ = ("_dim", "_head_sep", "_kv_fmt", "_levels", "_order", "_order_set", "_reset", "_sep", "_width")
    _configured: ClassVar[bool] = False

    def __init__(
        self,
        *,
        order: Sequence[str] = DEFAULT_ORDER,
        sep: str = DEFAULT_SEP,
        head_sep: str = DEFAULT_HEAD_SEP,
        kv_fmt: str = DEFAULT_KV_FMT,
        level_width: int = DEFAULT_LEVEL_WIDTH,
        colors: bool = True,
        stream: TextSink = DEFAULT_STREAM,
    ) -> None:
        self._order = tuple(order)
        self._order_set = frozenset(order)
        self._sep, self._head_sep, self._kv_fmt, self._width = sep, head_sep, kv_fmt, level_width
        match colors and stream.isatty():  # no ANSI codes into pipes or files
            case True:
                palette, self._dim, self._reset = LEVEL_COLORS, DIM, RESET
            case _:
                palette, self._dim, self._reset = dict.fromkeys(LEVEL_COLORS, ""), "", ""
        self._levels = {lvl: f"{color}{lvl.upper():<{level_width}}{self._reset}" for lvl, color in palette.items()}

    def __call__(self, _logger: WrappedLogger, _method: str, event_dict: EventDict) -> str:
        ts = event_dict.pop(TIMESTAMP_KEY, "")
        level = event_dict.pop(LEVEL_KEY, "")
        event = event_dict.pop(EVENT_KEY, "")
        exc = event_dict.pop(EXCEPTION_KEY, "")
        keys = [k for k in self._order if k in event_dict] + sorted(event_dict.keys() - self._order_set)
        label = self._levels.get(level) or f"{level.upper():<{self._width}}"
        head = self._head_sep.join((f"{self._dim}{ts}{self._reset}", label, str(event)))
        line = self._sep.join((head, *(self._kv_fmt.format(key=k, value=event_dict[k]) for k in keys)))
        return "\n".join(filter(None, (line, exc)))

    ############################################################

    ##### BOOTSTRAP #####

    @staticmethod
    def encode_json(event_dict: EventDict, default: Callable[[Any], Any] | None = None) -> bytes:
        """msgspec (C-backed) serializer, json.dumps-compatible: structlog's `default` hook is msgspec's `enc_hook`."""
        return msgspec.json.encode(event_dict, enc_hook=default)

    @classmethod
    def setup(
        cls,
        *,
        env: str = DEFAULT_ENV,
        level: int = DEFAULT_LEVEL,
        order: Sequence[str] = DEFAULT_ORDER,
        stream: TextIO = DEFAULT_STREAM,
        **renderer_kwargs: Any,
    ) -> None:
        """Configure structlog for the given env — the first call marks the process configured."""
        shared: list[Processor] = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]
        match env.lower():
            case Env.PROD:
                renderer: Processor = structlog.processors.JSONRenderer(serializer=cls.encode_json)
                factory: Any = structlog.BytesLoggerFactory(file=stream.buffer)  # msgspec emits bytes
            case Env.DEV | Env.LOCAL:
                renderer = ELogger(order=order, stream=stream, **renderer_kwargs)
                factory = structlog.PrintLoggerFactory(file=stream)
            case unknown:
                msg = f"Unknown env {unknown!r}; expected one of {[e.value for e in Env]}"
                raise ValueError(msg)

        structlog.configure(
            processors=[*shared, renderer],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            logger_factory=factory,
            cache_logger_on_first_use=True,
        )
        cls._configured = True

    @classmethod
    def load(cls) -> Any:
        """The process logger: setup with the app env runs here, on first use, never at import.

        `bind()` materializes the lazy proxy structlog hands back.
        ### the bound-logger class is polymorphic across structlog's stdlib/native wrapper variants:
        ### the surface is structlog's own untyped edge."""
        match cls._configured:
            case False:
                cls.setup(env=st.app.app_env)
            case _:
                pass
        return structlog.get_logger().bind()


##### RUNTIME TYPE CHECKING #####
ELogger = beartype.beartype(ELogger)

##### SINGLETON #####
### first attribute access only: reading env and configuring structlog must not run at import.
logger: LazyProxy[BindableLogger] = LazyProxy(ELogger.load)

### projects import `setup`/`encode_json` from the module: the class surface stays reachable, no underscore.
setup = ELogger.setup
encode_json = ELogger.encode_json
