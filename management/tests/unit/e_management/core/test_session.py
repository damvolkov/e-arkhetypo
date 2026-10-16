"""tests/unit/e_management/core/session: the serializable shadow of the walk — defaults, readiness, round-trip values."""

import msgspec

from e_management.core.session import Session


def test_session_defaults_every_switch_on_and_ready_false() -> None:
    session = Session()
    assert session.template == session.name == session.dest == ""
    assert session.off == session.drop == session.ci_off == ()
    assert session.at == ""
    assert session.trail == ()
    assert session.answers == {}
    assert session.ready is False


def test_session_is_ready_only_with_template_name_and_destination() -> None:
    assert Session(template="api", name="myapp").ready is False
    assert Session(template="api", name="myapp", dest="../e-myapp").ready is True


def test_session_carries_unit_tests_on_by_default() -> None:
    assert Session().verify_tests is True


def test_session_round_trips_through_json_values(tmp_path) -> None:

    session = Session(
        template="api",
        name="myapp",
        off=("websockets",),
        drop=("adapters/redis", "core/proxy"),
        ci_off=("docs",),
        dest=str(tmp_path / "e-myapp"),
        at="tools-core",
        trail=("system", "name"),
        answers={"system": ("api",), "name": ("myapp",)},
    )
    assert msgspec.json.decode(msgspec.json.encode(session), type=Session) == session
