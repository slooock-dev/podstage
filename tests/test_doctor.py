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
# Every backend is checked whether a profile uses it or not, so the answer to
# "can this machine do moonshine at all" is on screen before anyone picks it.
# Use decides SEVERITY only: an unused backend must never turn doctor red.

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


def test_avahi_is_not_required_for_a_moonshine_only_setup(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor.shutil, "which", lambda _n: None)
    res = doctor.check_avahi()
    assert res.status is doctor.Status.OK
    assert "moonshine announces itself" in res.detail
    # With a sunshine profile in the mix the warning comes back.
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "a"\n'
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    assert doctor.check_avahi().status is doctor.Status.WARN


# -- grouping ----------------------------------------------------------------

def test_by_group_follows_the_declared_order_and_drops_empties():
    def mk(name, group):
        return doctor.CheckResult(name, doctor.Status.OK, "", group=group)

    results = [mk("c", "moonshine"), mk("a", doctor.GROUP_HOST),
               mk("b", doctor.GROUP_STREAMING)]
    assert [g for g, _ in doctor.by_group(results)] == [
        doctor.GROUP_HOST, doctor.GROUP_STREAMING, "moonshine"]
    assert [r.name for _, rows in doctor.by_group(results) for r in rows] == \
        ["a", "b", "c"]


def test_base_image_row_says_why_it_is_there(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (0, "abc123"))
    monkeypatch.setattr(doctor.runtime, "image_is_stale",
                        lambda image="", backend=None: False)
    assert "base image for the moonshine backend" in doctor.check_image().detail
    # With a sunshine profile present it is just the streaming image again.
    _cfg_with(tmp_path, monkeypatch, '[[sessions]]\nname = "a"\n')
    assert "base image" not in doctor.check_image().detail


# -- both backends are always reported ---------------------------------------

def test_every_backend_group_is_reported_whatever_the_profiles_use(
        tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch, '[[sessions]]\nname = "a"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (0, "x"))
    groups = {r.group for r in doctor.run_all()}
    assert groups == {doctor.GROUP_HOST, doctor.GROUP_STREAMING,
                      "sunshine", "moonshine"}


def test_an_unused_backend_never_produces_a_blocker(tmp_path, monkeypatch):
    """Otherwise `podstage doctor` would exit 1 on every install that simply
    does not use moonshine."""
    _cfg_with(tmp_path, monkeypatch, '[[sessions]]\nname = "a"\n')
    # Nothing built, no Vulkan encode reported: the worst case.
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10:
                        (1, "") if "moonshine" in " ".join(cmd) else (0, ""))
    for res in (doctor.check_moonshine_image(), doctor.check_moonshine_gpu()):
        # Neutral, not green: "cannot run here" must not read as an all-clear.
        assert res.status is doctor.Status.INFO, res
        assert not res.fix
    assert "no profile uses it" in doctor.check_moonshine_image().detail


def test_the_same_gaps_block_once_a_profile_uses_the_backend(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10:
                        (1, "") if "moonshine" in " ".join(cmd) else (0, ""))
    res = doctor.check_moonshine_image()
    assert res.status is doctor.Status.FAIL
    assert res.fix == doctor.MOONSHINE_BUILD_FIX


# -- the GPU gate ------------------------------------------------------------

_VULKANINFO = """
	VK_KHR_video_encode_av1                       : extension revision 1
	VK_KHR_video_encode_h264                      : extension revision 14
	VK_KHR_video_encode_h265                      : extension revision 14
		queueFlags = QUEUE_TRANSFER_BIT | QUEUE_VIDEO_ENCODE_BIT_KHR
"""


def test_parse_video_encode_reads_queue_and_codecs():
    has_queue, codecs = doctor.parse_video_encode(_VULKANINFO)
    assert has_queue is True
    assert set(codecs) == {"H.264", "HEVC", "AV1"}


def test_parse_video_encode_on_a_gpu_without_an_encode_queue():
    # Decode-only extensions must not be mistaken for encode support.
    has_queue, codecs = doctor.parse_video_encode(
        "VK_KHR_video_decode_h264\nqueueFlags = QUEUE_GRAPHICS_BIT\n")
    assert has_queue is False and codecs == []


def test_gpu_gate_reports_the_codecs_it_found(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10: (0, _VULKANINFO)
                        if "run" in cmd else (0, ""))
    res = doctor.check_moonshine_gpu()
    assert res.status is doctor.Status.OK
    assert "H.264" in res.detail and "AV1" in res.detail


def test_gpu_gate_is_a_hardware_fact_with_no_fix(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10: (0, "no video here")
                        if "run" in cmd else (0, ""))
    res = doctor.check_moonshine_gpu()
    assert res.status is doctor.Status.FAIL
    assert not res.fix
    assert "sunshine backend is unaffected" in res.detail


def test_gpu_gate_needs_the_runtime_image_first(tmp_path, monkeypatch):
    _cfg_with(tmp_path, monkeypatch,
              '[[sessions]]\nname = "b"\nbackend = "moonshine"\n')
    monkeypatch.setattr(doctor, "_run", lambda cmd, timeout=10: (1, ""))
    res = doctor.check_moonshine_gpu()
    assert res.status is doctor.Status.OK
    assert "needs the runtime image" in res.detail


# -- what a config change can change -----------------------------------------

def test_config_signature_tracks_only_what_the_checks_read():
    from podstage.config import AppConfig, SessionConfig

    base = AppConfig(sessions=[SessionConfig(name="a")])
    same = AppConfig(sessions=[SessionConfig(name="a")], language="de",
                     preview_keep_last=False, mouse_keyboard=True)
    assert doctor.config_signature(base) == doctor.config_signature(same)

    for changed in (
        AppConfig(sessions=[SessionConfig(name="a", backend="moonshine")]),
        AppConfig(sessions=[SessionConfig(name="a", sunshine_port_base=48989)]),
        AppConfig(sessions=[SessionConfig(name="a"), SessionConfig(name="b")]),
        AppConfig(sessions=[SessionConfig(name="a")],
                  experimental={"gamepad_ds5": True}),
    ):
        assert doctor.config_signature(base) != doctor.config_signature(changed)


def test_info_rows_never_count_as_blockers_or_warnings(tmp_path, monkeypatch):
    """The CLI summary and the Setup headline both count FAIL and WARN; an
    unused backend must land outside both."""
    _cfg_with(tmp_path, monkeypatch, '[[sessions]]\nname = "a"\n')
    monkeypatch.setattr(doctor, "_run",
                        lambda cmd, timeout=10:
                        (1, "") if "moonshine" in " ".join(cmd) else (0, ""))
    results = doctor.run_all()
    info = [r for r in results if r.status is doctor.Status.INFO]
    assert info, "expected the unused backend to report neutrally"
    assert all(r.status is not doctor.Status.FAIL for r in info)
    assert all(r.status is not doctor.Status.WARN for r in info)


def test_one_crashing_check_does_not_take_the_report_down(monkeypatch):
    """The Setup page renders whatever run_all returns; an exception used to
    leave it with no rows at all and every other verdict hidden."""
    def boom():
        raise RuntimeError("podman went missing")

    monkeypatch.setattr(doctor, "ALL_CHECKS",
                        [(boom, doctor.GROUP_HOST),
                         (lambda: doctor.CheckResult("fine", doctor.Status.OK, ""),
                          doctor.GROUP_HOST)])
    results = doctor.run_all()
    assert [r.name for r in results] == ["boom", "fine"]
    assert results[0].status is doctor.Status.FAIL
    assert "podman went missing" in results[0].detail
