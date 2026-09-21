"""CLI command structure: sandbox owns the profile lifecycle, session the
running stream. Parse-only, no handler runs."""

import argparse

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
    # Acts on the one running container, so it takes no profile name.
    gr = p.parse_args(["session", "gamepad-reconnect"])
    assert gr.func is cli.cmd_session_gamepad_reconnect
    assert gr.hold_ms == 3000


def test_moved_flags_travel_with_their_verbs():
    p = cli.build_parser()
    a = p.parse_args(["sandbox", "add", "x", "--backend", "moonshine",
                      "--fixed-resolution", "--mount", "/opt/g:rw",
                      "--library-rw"])
    assert (a.backend, a.fixed_resolution, a.mount) == ("moonshine", True, ["/opt/g:rw"])
    assert a.library_rw is True
    assert p.parse_args(["sandbox", "add", "x"]).library_rw is False
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


def test_runtime_owns_prune_images():
    p = cli.build_parser()
    assert (p.parse_args(["runtime", "prune-images"]).func
            is cli.cmd_runtime_prune_images)


def test_prune_images_refuses_while_a_session_runs(monkeypatch, capsys):
    """`podman image rm -f` stops containers using the image. Rebuilding
    during a session leaves that session's image untagged and labelled, so an
    unguarded prune would kill the live stream."""
    from podstage.core import runtime as rt

    monkeypatch.setattr(cli.runtime, "status",
                        lambda: rt.RuntimeStatus(running=True, client="deck"))
    called = []
    monkeypatch.setattr(cli.runtime, "prune_stale_images",
                        lambda: called.append(1))

    rc = cli.cmd_runtime_prune_images(argparse.Namespace())

    assert rc == 1
    assert called == []
    assert "session is running" in capsys.readouterr().err


def test_prune_images_runs_when_idle(monkeypatch, capsys):
    from podstage.core import runtime as rt

    monkeypatch.setattr(cli.runtime, "status",
                        lambda: rt.RuntimeStatus(running=False, client=None))
    monkeypatch.setattr(cli.runtime, "prune_stale_images", lambda: (2, 7662782561))

    assert cli.cmd_runtime_prune_images(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "2" in out and "7.7 GB" in out
