"""infra/logger: structured JSON in prod, ordered plain text in dev/local.

Nothing loads at import: `setup` and the `logger` singleton run on first use, exactly once per process."""

import functools
import logging
import sys
from collections.abc import (
    Callable,
    Mapping,
    Sequence,
)
from types import MappingProxyType
from typing import ClassVar, Final, Protocol, TextIO, TypedDict, Unpack, runtime_checkable

import beartype
import msgspec
import structlog
from structlog.typing import (
    BindableLogger,
    EventDict,
    Processor,
    WrappedLogger,
)

from e_infra.infra.config.infra import Env
from e_infra.infra.proxy import LazyProxy


##### TYPES #####
@runtime_checkable
class TextSink(Protocol):
    """What ELogger genuinely consumes from a stream: the tty probe at construction. Nothing else."""

    def isatty(self) -> bool: ...


### a value a log line carries, or a serializer's fallback hands back: anything at all is the contract.
type Value = object  # ast-grep-ignore: object-annotation


### what a composition root hands `setup` to mask every line before it is rendered: a line in, a line out.
type Redact = Callable[[EventDict], EventDict]


class RendererOptions(TypedDict, total=False):
    """The dev renderer's own knobs, as `ELogger` takes them (`order` and `stream` are `setup`'s)."""

    sep: str
    head_sep: str
    kv_fmt: str
    level_width: int
    colors: bool


##### DEFAULTS #####
DEFAULT_ENV: Final[Env] = Env.DEV
DEFAULT_LEVEL: Final[int] = logging.INFO
DEFAULT_ORDER: Final[Sequence[str]] = ()
DEFAULT_SEP: Final[str] = " || "
DEFAULT_HEAD_SEP: Final[str] = " | "
DEFAULT_KV_FMT: Final[str] = "{key}: {value}"
DEFAULT_LEVEL_WIDTH: Final[int] = 8
DEFAULT_STREAM: Final[TextIO] = sys.stdout

##### EVENT DICT KEYS (SET BY STRUCTLOG PROCESSORS) #####
TIMESTAMP_KEY: Final[str] = "timestamp"
LEVEL_KEY: Final[str] = "level"
EVENT_KEY: Final[str] = "event"
EXCEPTION_KEY: Final[str] = "exception"

##### ANSI #####
RESET: Final[str] = "\033[0m"
DIM: Final[str] = "\033[2m"
LEVEL_COLORS: Final[Mapping[str, str]] = MappingProxyType({
    "debug": "\033[36m",
    "info": "\033[32m",
    "warning": "\033[33m",
    "error": "\033[31m",
    "critical": "\033[1;31m",
})  # fmt: skip


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
        ### No ANSI codes into pipes or files.
        match colors and stream.isatty():
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

    @staticmethod
    def _setup_redact(redact: Redact, _logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        return redact(event_dict)

    ############################################################

    ##### BOOTSTRAP #####

    @staticmethod
    def encode_json(event_dict: EventDict, default: Callable[[Value], Value] | None = None) -> bytes:
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
        extra: Sequence[Processor] = (),
        redact: Redact | None = None,
        **options: Unpack[RendererOptions],
    ) -> None:
        """Configure structlog for the given env — the first call marks the process configured. `extra` processors run
        before the renderer, after the shared ones: the composition root hands the tracer's there (a log line inside a
        span becomes one of its events), so this module never imports what it hands. `redact`, when given, runs over every
        line after its context is merged and its exception rendered, before the level, the timestamp and the renderer:
        what it masks never reaches a stream; the patterns are the root's data, never this module's."""
        shared: list[Processor] = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            *([functools.partial(cls._setup_redact, redact)] if redact is not None else []),
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            *extra,
        ]
        match env.lower():
            case Env.PROD:
                renderer: Processor = structlog.processors.JSONRenderer(serializer=cls.encode_json)
                ### msgspec emits bytes.
                factory: Callable[..., WrappedLogger] = structlog.BytesLoggerFactory(file=stream.buffer)
            case Env.DEV | Env.LOCAL:
                renderer = ELogger(order=order, stream=stream, **options)
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
    def load(cls) -> BindableLogger:
        """The process logger: an unconfigured process is set up with the default env here, on first use, never at import;
        a composition root that reads APP_ENV calls `setup` first.

        `bind()` materializes the lazy proxy structlog hands back.
        ### the bound-logger class is polymorphic across structlog's stdlib/native wrapper variants:
        ### the surface is structlog's own untyped edge."""
        match cls._configured:
            case False:
                cls.setup()
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
