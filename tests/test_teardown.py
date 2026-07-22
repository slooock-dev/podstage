"""Tests for the detection-based uninstall."""

from pathlib import Path

from podstage import config
from podstage.core import teardown, udev


def _fake_system(monkeypatch, tmp_path: Path, *, udev_present=True, ports=None,
                 mdns=False, cdi=False, image=False):
    monkeypatch.setattr(udev, "STATIC_DEST", tmp_path / "99.rules")
    monkeypatch.setattr(udev, "OWNER_DEST", tmp_path / "71.rules")
    if udev_present:
        (tmp_path / "99.rules").write_text("x")
    cdi_spec = tmp_path / "nvidia.yaml"
    if cdi:
        cdi_spec.write_text("x")
    monkeypatch.setattr(teardown, "CDI_SPEC", cdi_spec)
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


def test_leftovers_exclude_shared_by_default(monkeypatch, tmp_path):
    _fake_system(monkeypatch, tmp_path, udev_present=False, mdns=True, cdi=True)
    assert teardown.leftovers() == []
    assert {a.key for a in teardown.leftovers(include_shared=True)} == {"mdns", "cdi"}
