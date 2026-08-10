"""CLI command structure: sandbox owns the profile lifecycle, session the
running stream. Parse-only, no handler runs."""

import pytest

from podstage import cli


def test_sandbox_owns_the_profile_verbs():
    p = cli.build_parser()
    assert p.parse_args(["sandbox", "list"]).func is cli.cmd_sandbox_list
    assert p.parse_args(["sandbox", "add", "x"]).func is cli.cmd_sandbox_add
    assert p.parse_args(["sandbox", "remove", "x"]).func is cli.cmd_sandbox_remove
    assert p.parse_args(["sandbox", "setup", "x"]).func is cli.cmd_sandbox_setup
    assert p.parse_args(["sandbox", "login", "x"]).func is cli.cmd_sandbox_login
    assert (p.parse_args(["sandbox", "clear-overlay", "x"]).func
            is cli.cmd_sandbox_clear_overlay)


def test_session_owns_the_stream_verbs():
    p = cli.build_parser()
    assert p.parse_args(["session", "start", "x"]).func is cli.cmd_session_start
    assert p.parse_args(["session", "stop", "x"]).func is cli.cmd_session_stop
    assert p.parse_args(["session", "status", "x"]).func is cli.cmd_session_status
    assert (p.parse_args(["session", "pair", "x", "1234"]).func
            is cli.cmd_session_pair)


def test_moved_flags_travel_with_their_verbs():
    p = cli.build_parser()
    a = p.parse_args(["sandbox", "add", "x", "--backend", "moonshine",
                      "--fixed-resolution", "--mount", "/opt/g:rw"])
    assert (a.backend, a.fixed_resolution, a.mount) == ("moonshine", True, ["/opt/g:rw"])
    s = p.parse_args(["session", "start", "x", "--mode", "probe"])
    assert s.mode == "probe"


@pytest.mark.parametrize("argv", [
    ["session", "list"],
    ["session", "add", "x"],
    ["session", "remove", "x"],
    ["session", "setup", "x"],
    ["session", "login", "x"],
    ["session", "clear-overlay", "x"],
    ["sandbox", "start", "x"],
    ["sandbox", "stop", "x"],
    ["sandbox", "status", "x"],
    ["sandbox", "pair", "x", "1234"],
])
def test_moved_verbs_fail_hard(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args(argv)
    assert e.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_top_level_help_names_both_subcommands():
    help_text = cli.build_parser().format_help()
    assert "manage sandboxes (isolated Steam profiles)" in help_text
    assert "manage the running streaming session" in help_text


@pytest.mark.parametrize("argv", [["sandbox"], ["session"]])
def test_bare_subcommand_requires_an_action(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args(argv)
    assert e.value.code == 2
    assert "required: action" in capsys.readouterr().err
