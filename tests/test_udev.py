"""Tests for the host udev rule generation (the one root-gated setup step)."""

from podstage.core import udev


def test_owner_rule_grants_exactly_the_user():
    text = udev.owner_rule_text(user="alice")
    assert text.count('OWNER="alice"') == 4
    # DAC is purely owner-based — groups don't map through the rootless userns.
    assert "GROUP" not in text


def test_owner_rule_covers_streaming_devices_and_uinput():
    text = udev.owner_rule_text(user="alice")
    for match in ('ATTRS{name}=="Sunshine*"',
                  'ATTRS{name}=="*passthrough*"', 'ATTRS{id/vendor}=="28de"'):
        assert match in text
    assert 'KERNEL=="uinput"' in text
    # The bundled Sunshine names all its devices "Sunshine …" / "… passthrough"
    # — the old Wolf* match was a leftover and is gone.
    assert "Wolf" not in text


def test_static_rule_pins_seat9_without_group():
    text = udev.STATIC_SRC.read_text()
    rules = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    for match in ('ATTRS{name}=="*passthrough*"', 'ATTRS{id/vendor}=="28de"'):
        assert any(match in ln for ln in rules)
    assert sum('ENV{ID_SEAT}="seat9"' in ln for ln in rules) == 3
    assert all('MODE="0600"' in ln for ln in rules)
    assert not any("Wolf" in ln for ln in rules)
    # DAC is purely owner-based (generated rule) — no GROUP grants here.
    assert not any("GROUP" in ln for ln in rules)


def test_install_shell_single_root_line():
    staged = {"static": udev.STATIC_SRC,
              "owner": udev.STAGING_DIR / udev.OWNER_DEST.name}
    shell = udev.install_shell(staged)
    assert "sudo" not in shell  # pkexec runs the whole line as root already
    assert str(udev.STATIC_DEST) in shell
    assert str(udev.OWNER_DEST) in shell
    assert "udevadm control --reload" in shell
    assert "udevadm trigger --sysname-match=uinput" in shell


def test_install_commands_are_sudo_prefixed():
    staged = {"static": udev.STATIC_SRC,
              "owner": udev.STAGING_DIR / udev.OWNER_DEST.name}
    for cmd in udev.install_commands(staged):
        assert cmd.startswith("sudo ")
