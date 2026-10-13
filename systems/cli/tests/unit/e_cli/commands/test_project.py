"""tests/unit/e_cli/commands/project: the demo domain through the real `ecli` — auth gate, validation, rendering."""

TOKEN = ("--token", "tk-test-0001")


def test_project_create_requires_a_login(ecli) -> None:
    code, _, err = ecli("project", "create", "demo")
    assert code == 3
    assert "not authenticated" in err


def test_project_create_then_list_shows_it(ecli) -> None:
    assert ecli(*TOKEN, "project", "create", "demo", "--description", "first", "--state", "active")[0] == 0
    code, out, _ = ecli("project", "list")
    assert code == 0
    assert "demo" in out
    assert "active" in out
    assert "first" in out


def test_project_list_empty_says_how_to_start(ecli) -> None:
    _, out, _ = ecli("project", "list")
    assert "no projects yet" in out


def test_project_create_refuses_an_invalid_name_quoting_the_rule(ecli) -> None:
    code, _, err = ecli(*TOKEN, "project", "create", "Bad_Name")
    assert code == 5
    assert "[a-z][a-z0-9-]" in err, "the rule must survive rich markup"


def test_project_create_refuses_a_duplicate(ecli) -> None:
    ecli(*TOKEN, "project", "create", "demo")
    code, _, err = ecli(*TOKEN, "project", "create", "demo")
    assert code == 5
    assert "already exists" in err


def test_project_env_set_then_list(ecli) -> None:
    ecli(*TOKEN, "project", "create", "demo")
    assert ecli(*TOKEN, "project", "env", "set", "demo", "API_URL", "https://x")[0] == 0
    code, out, _ = ecli("project", "env", "list", "demo")
    assert code == 0
    assert "API_URL" in out
    assert "https://x" in out


def test_project_env_list_empty_says_so(ecli) -> None:
    ecli(*TOKEN, "project", "create", "demo")
    _, out, _ = ecli("project", "env", "list", "demo")
    assert "no variables" in out


def test_project_env_set_refuses_a_lowercase_key(ecli) -> None:
    ecli(*TOKEN, "project", "create", "demo")
    code, _, err = ecli(*TOKEN, "project", "env", "set", "demo", "lower", "v")
    assert code == 5
    assert "invalid variable name" in err


def test_project_remove_unknown_is_refused(ecli) -> None:
    code, _, err = ecli(*TOKEN, "project", "remove", "ghost")
    assert code == 5
    assert "no project named 'ghost'" in err


def test_project_remove_is_undone_by_history(ecli) -> None:
    ecli(*TOKEN, "project", "create", "demo")
    assert ecli(*TOKEN, "project", "remove", "demo")[0] == 0
    assert "no projects yet" in ecli("project", "list")[1]
    assert ecli("history", "undo")[0] == 0
    assert "demo" in ecli("project", "list")[1]
