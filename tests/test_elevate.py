import pytest

from podstage.core import elevate


def test_fix_shell_strips_every_sudo():
    shell, needs_root = elevate.fix_shell(
        "sudo firewall-cmd --permanent --add-service=mdns && sudo firewall-cmd --reload")
    assert shell == "firewall-cmd --permanent --add-service=mdns && firewall-cmd --reload"
    assert needs_root


def test_fix_shell_user_command_untouched():
    shell, needs_root = elevate.fix_shell(
        "systemctl --user disable --now app-dev.lizardbyte.app.Sunshine.service")
    assert "sudo" not in shell
    assert not needs_root


def test_fix_shell_rejects_mixed_pipeline():
    with pytest.raises(ValueError):
        elevate.fix_shell("podman save img | sudo podman load")
