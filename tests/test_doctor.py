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
