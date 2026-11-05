"""Tests for the detection-based uninstall."""

from pathlib import Path

from podstage import config
from podstage.core import desktop, doctor, teardown, udev


def _fake_system(monkeypatch, tmp_path: Path, *, udev_present=True, ports=None,
                 mdns=False, cdi=False, image=False, integration=False):
    # conftest already redirects the desktop paths into tmp_path
    monkeypatch.setattr(desktop, "_refresh_menu", lambda: None)
    if integration:
        desktop.MENU_FILE.parent.mkdir(parents=True)
        desktop.MENU_FILE.write_text("[Desktop Entry]\n")
        desktop.ICON_DEST.parent.mkdir(parents=True)
        desktop.ICON_DEST.write_text("<svg/>")
    monkeypatch.setattr(udev, "STATIC_DEST", tmp_path / "99.rules")
    monkeypatch.setattr(udev, "OWNER_DEST", tmp_path / "71.rules")
    if udev_present:
        (tmp_path / "99.rules").write_text("x")
    cdi_spec = tmp_path / "nvidia.yaml"
    if cdi:
        cdi_spec.write_text("x")
    monkeypatch.setattr(teardown, "CDI_SPEC", cdi_spec)
    monkeypatch.setattr(teardown, "_firewall_kind", lambda: "firewalld")
    monkeypatch.setattr(teardown, "_open_stream_ports", lambda: ports or [])
    monkeypatch.setattr(teardown, "_mdns_allowed", lambda: mdns)
    monkeypatch.setattr(teardown, "_image_present", lambda: image)
    monkeypatch.setattr(config, "SESSIONS_HOME_ROOT", tmp_path / "homes")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")


def test_inventory_detects_and_classifies(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=True,
                 ports=["47989/tcp"], mdns=True, cdi=True, image=True)
    arts = {a.key: a for a in teardown.inventory()}
    assert arts["udev"].present and arts["udev"].root and not arts["udev"].shared
    assert arts["ports"].present and arts["ports"].detail == "47989/tcp"
    assert arts["mdns"].shared and arts["cdi"].shared  # other software's too
    assert arts["image"].present
    assert not arts["sandboxes"].present  # no homes dir
    assert not arts["data"].present and not arts["config"].present


def test_root_steps_keep_shared_by_default(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=True,
                 ports=["47989/tcp", "48000/udp"], mdns=True, cdi=True)
    arts = teardown.inventory()
    steps = teardown.root_steps(arts)
    joined = " && ".join(steps)
    assert "rm -f" in steps[0] and "99.rules" in steps[0]
    assert "udevadm control --reload" in steps
    assert "udevadm trigger --sysname-match=uinput" in steps
    assert "--remove-port=47989/tcp --remove-port=48000/udp" in joined
    assert joined.count("firewall-cmd --reload") == 1
    # shared artifacts stay
    assert "mdns" not in joined and "nvidia.yaml" not in joined
    # ... unless explicitly included
    all_steps = " && ".join(teardown.root_steps(arts, include_shared=True))
    assert "--remove-service=mdns" in all_steps and "nvidia.yaml" in all_steps


def test_root_steps_empty_when_nothing_installed(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=False)
    assert teardown.root_steps(teardown.inventory()) == []


def test_remove_user_artifacts(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=False)
    (tmp_path / "homes/deck/.local").mkdir(parents=True)
    (tmp_path / "data/overlays").mkdir(parents=True)
    (tmp_path / "cfg").mkdir()
    monkeypatch.setattr(teardown.runtime, "stop", lambda: False)

    results = dict(teardown.remove_user_artifacts())

    assert results["sandbox deck"] == "removed"
    assert not (tmp_path / "homes").exists()  # root removed once empty
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "cfg").exists()
    assert not teardown.leftovers()


def test_remove_keeps_sandboxes_on_request(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=False)
    box = tmp_path / "homes/deck"
    box.mkdir(parents=True)
    monkeypatch.setattr(teardown.runtime, "stop", lambda: False)

    teardown.remove_user_artifacts(keep_sandboxes=True)

    assert box.exists()
    left = teardown.leftovers()
    assert [a.key for a in left] == ["sandboxes"]


def test_desktop_integration_is_detected_and_removed(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=False, integration=True)
    monkeypatch.setattr(teardown.runtime, "stop", lambda: False)
    art = {a.key: a for a in teardown.inventory()}["desktop"]
    assert art.present and not art.root and not art.shared
    assert "podstage.desktop" in art.detail

    results = dict(teardown.remove_user_artifacts())

    assert results["desktop integration"] == "removed menu entry, icon"
    assert not desktop.MENU_FILE.exists() and not desktop.ICON_DEST.exists()
    assert not teardown.leftovers()


def test_leftovers_exclude_shared_by_default(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=False, mdns=True, cdi=True)
    assert teardown.leftovers() == []
    assert {a.key for a in teardown.leftovers(include_shared=True)} == {"mdns", "cdi"}


def test_root_steps_remove_ufw_rules(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=False,
                 ports=["47989/tcp", "48000/udp"], mdns=True)
    monkeypatch.setattr(teardown, "_firewall_kind", lambda: "ufw")
    arts = teardown.inventory()

    joined = " && ".join(teardown.root_steps(arts, include_shared=True))

    assert "ufw delete allow 47989/tcp" in joined
    assert "ufw delete allow 48000/udp" in joined
    assert "ufw delete allow 5353/udp" in joined
    assert "firewall-cmd" not in joined  # never mix the two


def test_ufw_artifacts_come_from_ufw_rules(monkeypatch, tmp_path):
    from podstage import config

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[sessions]]\nname = "a"\n')
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    rules = tmp_path / "user.rules"
    rules.write_text(
        "-A ufw-user-input -p tcp -m tcp --dport 47989 -j ACCEPT\n"
        "-A ufw-user-input -p udp -m udp --dport 47998:48000 -j ACCEPT\n"
        "-A ufw-user-input -p udp -m udp --dport 5353 -j ACCEPT\n")
    monkeypatch.setattr(doctor, "UFW_USER_RULES", rules)
    monkeypatch.setattr(teardown, "_firewall_kind", lambda: "ufw")

    arts = {a.key: a for a in teardown.inventory()}

    # only the exact single-port rule counts as podstage's own
    assert arts["ports"].detail == "47989/tcp"
    assert arts["mdns"].present
