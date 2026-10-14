"""tests/unit/e_cli/commands/history: the journal as a user sees it — list, undo in order, failed runs never filed."""

TOKEN = ("--token", "tk-test-0001")


def test_history_list_empty_says_so(ecli) -> None:
    _, out, _ = ecli("history", "list")
    assert "nothing recorded" in out


def test_history_list_shows_runs_newest_first(ecli) -> None:
    ecli(*TOKEN, "project", "create", "demo")
    ecli(*TOKEN, "project", "env", "set", "demo", "KEY", "v")
    _, out, _ = ecli("history", "list")
    assert out.index("project env set") < out.index("project create")


def test_history_undo_walks_back_one_run_at_a_time(ecli) -> None:
    ecli(*TOKEN, "project", "create", "demo")
    ecli(*TOKEN, "project", "env", "set", "demo", "KEY", "v")
    assert "undid `project env set`" in ecli("history", "undo")[1]
    assert "no variables" in ecli("project", "env", "list", "demo")[1]
    assert "undid `project create`" in ecli("history", "undo")[1]
    code, _, err = ecli("history", "undo")
    assert code == 4
    assert "nothing to undo" in err


def test_history_failed_run_is_never_filed(ecli) -> None:
    ecli(*TOKEN, "project", "create", "demo")
    ecli(*TOKEN, "project", "create", "demo")
    _, out, _ = ecli("history", "list")
    assert out.count("project create") == 1
