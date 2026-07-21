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
