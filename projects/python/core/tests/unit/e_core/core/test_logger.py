"""e_core.core.logger: renderer, serializer and startup wiring."""

import io
import json
from typing import TYPE_CHECKING, Any, cast

import pytest

from e_core.core import logger as lg

if TYPE_CHECKING:
    from structlog.typing import EventDict, WrappedLogger


##### SETUP #####
@pytest.mark.parametrize("env", ["prod", "dev", "local"], ids=["prod", "dev", "local"])
async def test_setup(env: str) -> None:
    lg.setup(env=env)


async def test_setup_unknown_env() -> None:
    with pytest.raises(ValueError, match="Unknown env"):
        lg.setup(env="nope")


##### ENCODE_JSON #####
async def test_encode_json() -> None:
    assert json.loads(lg.encode_json({"event": "ok", "n": 1})) == {"event": "ok", "n": 1}


async def test_encode_json_default_hook() -> None:
    raw = lg.encode_json({"obj": object()}, default=str)
    assert "object object at" in raw.decode()


##### ELOGGER #####
class _TTYStream(io.TextIOWrapper):
    def isatty(self) -> bool:
        return True


def _sink(*, tty: bool = False) -> io.TextIOWrapper:
    return _TTYStream(io.BytesIO()) if tty else io.TextIOWrapper(io.BytesIO())


async def test_elogger_order() -> None:
    renderer = lg.ELogger(order=("request_id",), stream=_sink())
    event: EventDict = {"timestamp": "T", "level": "info", "event": "hello", "zeta": 1, "request_id": "r1"}
    assert renderer(cast("WrappedLogger", None), "info", event) == "T | INFO     | hello || request_id: r1 || zeta: 1"


async def test_elogger_colors() -> None:
    renderer = lg.ELogger(stream=_sink(tty=True))
    event: EventDict = {"timestamp": "T", "level": "warning", "event": "hi"}
    assert "\033[33m" in renderer(cast("WrappedLogger", None), "warning", event)


async def test_elogger_unknown_level() -> None:
    renderer = lg.ELogger(stream=_sink())
    event: EventDict = {"timestamp": "T", "level": "notice", "event": "hi"}
    assert "NOTICE" in renderer(cast("WrappedLogger", None), "notice", event)


async def test_elogger_traceback_appended() -> None:
    renderer = lg.ELogger(stream=_sink())
    event: EventDict = {"timestamp": "T", "level": "error", "event": "boom", "exception": "Traceback..."}
    line = renderer(cast("WrappedLogger", None), "error", event)
    assert line.endswith("Traceback...")


##### LAZY SINGLETON #####
async def test_logger_singleton_is_stable_after_first_touch() -> None:
    assert lg.logger is lg.logger


async def test_load_sets_up_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first load runs setup with the app env; the process ends up configured."""
    monkeypatch.setattr(lg.ELogger, "_configured", False)
    assert lg.ELogger.load() is not None
    assert lg.ELogger._configured is True


async def test_load_skips_setup_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lifespan that already called setup is never reconfigured by the lazy logger."""
    monkeypatch.setattr(lg.ELogger, "_configured", True)

    def refuse(**_: Any) -> None:
        pytest.fail("the lazy logger must not reconfigure an already-configured process")

    monkeypatch.setattr(lg.ELogger, "setup", refuse)
    assert lg.ELogger.load() is not None
