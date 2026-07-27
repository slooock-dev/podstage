from podstage import config
from podstage.core import doctor


def test_fw_range_covers_port():
    ranges = doctor._fw_open_ranges("1025-65535/tcp 5353/udp")
    assert doctor._fw_covered(47989, "tcp", ranges) is True   # inside the range
    assert doctor._fw_covered(48010, "tcp", ranges) is True
    assert doctor._fw_covered(5353, "udp", ranges) is True    # exact
    assert doctor._fw_covered(47998, "udp", ranges) is False  # udp not opened


def test_fw_exact_ports():
    ranges = doctor._fw_open_ranges("47989/tcp 48010/tcp")
    assert doctor._fw_covered(47989, "tcp", ranges) is True
    assert doctor._fw_covered(48000, "tcp", ranges) is False


def test_fw_empty_covers_nothing():
    ranges = doctor._fw_open_ranges("")
    assert doctor._fw_covered(47989, "tcp", ranges) is False


def test_fw_ignores_malformed_tokens():
    ranges = doctor._fw_open_ranges("garbage 80/tcp x-y/udp")
    assert doctor._fw_covered(80, "tcp", ranges) is True
    assert doctor._fw_covered(1234, "udp", ranges) is False


def test_stream_ports_default_base(tmp_path, monkeypatch):
    from podstage import config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.toml")
    assert doctor.stream_port_bases() == [47989]
    tcp, udp = doctor.stream_ports()
    assert tcp == [47984, 47989, 48010]
    assert udp == [47998, 47999, 48000, 48100, 48200]


def test_stream_ports_follow_custom_bases(tmp_path, monkeypatch):
    from podstage import config

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[sessions]]\nname = "a"\nsunshine_port_base = 48989\n'
                   '[[sessions]]\nname = "b"\nsunshine_port_base = 47989\n')
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    assert doctor.stream_port_bases() == [47989, 48989]
    tcp, udp = doctor.stream_ports()
    assert 48984 in tcp and 49010 in tcp   # shifted https/rtsp
    assert 48998 in udp and 49200 in udp   # shifted video / +2
    assert 47984 in tcp and 47998 in udp   # default base still covered


def test_stream_ports_unreadable_config_falls_back(tmp_path, monkeypatch):
    from podstage import config

    cfg = tmp_path / "config.toml"
    cfg.write_text("not [ valid toml")
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    assert doctor.stream_port_bases() == [47989]


def test_stream_firewall_warns_on_closed_custom_ports(tmp_path, monkeypatch):
    """Default-base ports open in firewalld, but the profile uses a custom
    base: the check must warn about the SHIFTED ports and the fix must add
    only those."""
    from podstage import config

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[sessions]]\nname = "a"\nsunshine_port_base = 48989\n')
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)

    def fake_run(cmd, timeout=10):
        if "--state" in cmd:
            return 0, "running"
        if "--list-ports" in cmd:
            return 0, ("47984/tcp 47989/tcp 48010/tcp "
                       "47998/udp 47999/udp 48000/udp 48100/udp 48200/udp")
        return 1, "unexpected"

    monkeypatch.setattr(doctor, "_run", fake_run)
    res = doctor.check_stream_firewall()
    assert res.status is doctor.Status.WARN
    assert "48984/tcp" in res.detail and "49200/udp" in res.detail
    assert "--add-port=48984/tcp" in res.fix
    assert "--add-port=47984/tcp" not in res.fix  # already open


def test_stream_firewall_ok_names_custom_base(tmp_path, monkeypatch):
    from podstage import config

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[sessions]]\nname = "a"\nsunshine_port_base = 48989\n')
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10:
                        (0, "running") if "--state" in cmd
                        else (0, "1025-65535/tcp 1025-65535/udp"))
    res = doctor.check_stream_firewall()
    assert res.status is doctor.Status.OK
    assert "48989" in res.detail


def test_uhid_check_off_and_on(tmp_path, monkeypatch):
    from podstage import config

    # feature off (no config): informational OK
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.toml")
    res = doctor.check_uhid()
    assert res.status is doctor.Status.OK and "off" in res.detail
    # feature on, /dev/uhid inaccessible: FAIL with the udev fix
    cfg = tmp_path / "config.toml"
    cfg.write_text("[experimental]\ngamepad_ds5 = true\n")
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    monkeypatch.setattr(doctor.os, "access", lambda p, m: False)
    res = doctor.check_uhid()
    if res.status is doctor.Status.FAIL:
        assert "uhid" in res.detail
    else:  # host without /dev/uhid at all also FAILs; OK impossible here
        raise AssertionError(res)


def test_owner_rule_covers_uhid():
    from podstage.core import udev

    text = udev.owner_rule_text("someone")
    assert 'KERNEL=="uhid"' in text and 'OWNER="someone"' in text


def test_udev_check_fails_without_owner_rule(tmp_path, monkeypatch):
    from podstage.core import udev

    static = tmp_path / "99-podstage-virtual-inputs.rules"
    static.write_text('SUBSYSTEMS=="input", ATTRS{name}=="*passthrough*", '
                      'ENV{ID_SEAT}="seat9", MODE="0600"\n'
                      'SUBSYSTEMS=="input", ATTRS{id/vendor}=="28de", '
                      'ENV{ID_SEAT}="seat9", MODE="0600"\n')
    monkeypatch.setattr(udev, "STATIC_DEST", static)
    monkeypatch.setattr(udev, "OWNER_DEST", tmp_path / "71-missing.rules")
    result = doctor.check_udev_rules()
    assert result.status is doctor.Status.FAIL
    assert "owner" in result.detail.lower() or "71-" in result.detail


def test_udev_check_ok_with_both_rules(tmp_path, monkeypatch):
    import getpass

    from podstage.core import udev

    static = tmp_path / "99-podstage-virtual-inputs.rules"
    static.write_text('*passthrough* 28de')
    owner = tmp_path / "71-podstage-input-owner.rules"
    owner.write_text(udev.owner_rule_text(getpass.getuser()))
    monkeypatch.setattr(udev, "STATIC_DEST", static)
    monkeypatch.setattr(udev, "OWNER_DEST", owner)
    assert doctor.check_udev_rules().status is doctor.Status.OK


# -- moonshine backend checks ------------------------------------------------
#
# Both are inert unless a profile selects the backend: it is opt-in, and its
# GPU requirement is narrower than Sunshine's, so warning about it on a
# machine that never uses it would be noise.

def _cfg_with(tmp_path, monkeypatch, body):
    cfg = tmp_path / "config.toml"
    cfg.write_text(body)
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    return cfg


def test_configured_backends_reads_the_profiles(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "a"\n'
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    assert doctor.configured_backends() == {"sunshine", "moonshine"}


def test_configured_backends_defaults_without_a_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "gone.toml")
    assert doctor.configured_backends() == {"sunshine"}


def test_moonshine_checks_are_silent_without_a_moonshine_profile(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch, '[[sessions]]\nname = "a"\n')
    # Would blow up if it ran podman; it must not get that far.
    monkeypatch.setattr(doctor, "_run", _boom)
    for check in (doctor.check_moonshine_image, doctor.check_moonshine_encode):
        res = check()
        assert res.status is doctor.Status.OK
        assert "not used" in res.detail


def _boom(*_a, **_kw):
    raise AssertionError("must not shell out")


def test_moonshine_image_check_asks_for_a_build(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (1, ""))
    res = doctor.check_moonshine_image()
    assert res.status is doctor.Status.FAIL
    assert res.fix == doctor.MOONSHINE_BUILD_FIX


def test_moonshine_encode_reads_the_upstream_codec_line(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    report = ("OK  Render nodes  renderD128\n"
              "OK  Codecs        H.264, HEVC, AV1\n"
              "WARN Sleep inhibit  (logind absent)\n")
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10: (0, report) if "run" in cmd else (0, ""))
    res = doctor.check_moonshine_encode()
    assert res.status is doctor.Status.OK
    assert "H.264, HEVC, AV1" in res.detail


def test_moonshine_encode_fails_on_a_gpu_without_vulkan_video(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    report = "OK  Render nodes  renderD128\nFAIL Codecs  none\n"
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10: (1, report) if "run" in cmd else (0, ""))
    res = doctor.check_moonshine_encode()
    assert res.status is doctor.Status.FAIL
    # A hardware fact, so no fix command is offered.
    assert not res.fix
    assert "sunshine backend" in res.detail


def test_moonshine_encode_admits_an_unreadable_report(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10: (125, "podman: error")
                        if "run" in cmd else (0, ""))
    res = doctor.check_moonshine_encode()
    assert res.status is doctor.Status.WARN
    assert "no codec line" in res.detail


def test_avahi_is_not_required_for_a_moonshine_only_setup(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor.shutil, "which", lambda _n: None)
    res = doctor.check_avahi()
    assert res.status is doctor.Status.OK
    assert "moonshine announces itself" in res.detail
    # With a Sunshine profile in the mix the warning comes back.
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "a"\n'
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    assert doctor.check_avahi().status is doctor.Status.WARN


# -- grouping ----------------------------------------------------------------

def test_run_all_stamps_groups_and_skips_unused_backends(tmp_path, monkeypatch):
    """A backend nobody uses contributes no rows at all: an inert
    'not used' line would be noise and would inflate the counters."""
    _cfg_with(tmp_path, monkeypatch, '[[sessions]]\nname = "a"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (0, "x"))
    names = {r.name: r.group for r in doctor.run_all()}
    assert names["podman"] == doctor.GROUP_HOST
    assert names["avahi"] == doctor.GROUP_STREAMING
    assert names["image"] == "sunshine"
    assert "moonshine image" not in names
    assert "moonshine encode" not in names


def test_moonshine_only_setup_keeps_the_base_but_drops_nothing_it_needs(
        tmp_path, monkeypatch):
    """Only the runtime image survives from the Sunshine side, and only
    because the moonshine image is built FROM it."""
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (0, "OK Codecs H.264"))
    monkeypatch.setattr(doctor.runtime, "image_is_stale",
                        lambda image="", backend=None: False)
    names = {r.name: r.group for r in doctor.run_all()}
    assert names["moonshine image"] == "moonshine"
    assert names["image"] == "sunshine"           # the base, kept on purpose
    assert names["podman"] == doctor.GROUP_HOST   # host checks always apply


def test_by_group_follows_the_declared_order_and_drops_empties():
    def mk(name, group):
        return doctor.CheckResult(name, doctor.Status.OK, "", group=group)

    results = [mk("c", "moonshine"), mk("a", doctor.GROUP_HOST),
               mk("b", doctor.GROUP_STREAMING)]
    assert [g for g, _ in doctor.by_group(results)] == [
        doctor.GROUP_HOST, doctor.GROUP_STREAMING, "moonshine"]
    assert [r.name for _, rows in doctor.by_group(results) for r in rows] == \
        ["a", "b", "c"]


def test_encode_check_offers_no_second_build_button(tmp_path, monkeypatch):
    """The 'moonshine image' row owns the build action."""
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (1, ""))
    res = doctor.check_moonshine_encode()
    assert res.status is doctor.Status.WARN
    assert not res.fix


def test_base_backend_group_survives_a_moonshine_only_setup(tmp_path, monkeypatch):
    """The moonshine image is built FROM the runtime image, so hiding the
    Sunshine group would hide a dependency that still has to be current."""
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (0, "OK Codecs H.264"))
    monkeypatch.setattr(doctor.runtime, "image_is_stale",
                        lambda image="", backend=None: False)
    rows = {r.name: r.group for r in doctor.run_all()}
    assert rows["image"] == "sunshine"
    assert rows["moonshine image"] == "moonshine"
    # The port conflict hits any backend, so it is not a Sunshine-only row.
    assert rows["sunshine-conflict"] == doctor.GROUP_STREAMING


def test_base_image_row_says_why_it_is_there(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (0, "abc123"))
    monkeypatch.setattr(doctor.runtime, "image_is_stale",
                        lambda image="", backend=None: False)
    assert "base image for the moonshine backend" in doctor.check_image().detail
    # With a Sunshine profile present it is just the streaming image again.
    _cfg_with(tmp_path, monkeypatch, '[[sessions]]\nname = "a"\n')
    assert "base image" not in doctor.check_image().detail
