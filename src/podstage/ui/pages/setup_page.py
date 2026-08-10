"""Setup page — doctor checks with one-click fixes.

Every root-gated fix runs through pkexec (graphical polkit password dialog) —
no copy/paste sudo. After each action the checks re-run automatically. The
goal: complete first-time setup by clicking top to bottom, then never see a
password again — the runtime container is rootless, so the udev rules install
here is the only root interaction podstage ever needs.

Doctor check names and details are shown verbatim: they are English technical
diagnostics shared with the CLI and are intentionally not translated.
"""

import subprocess

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import __version__, config
from ...core import (
    backends,
    desktop,
    doctor,
    elevate,
    runtime,
    teardown,
    udev,
    update,
)
from ..i18n import tr
from ..widgets import ElideLabel, card
from ..workers import start_action

_GLYPH = {doctor.Status.OK: ("●", "ok"),
          doctor.Status.WARN: ("▲", "warn"),
          doctor.Status.FAIL: ("✖", "fail"),
          doctor.Status.INFO: ("○", "info")}

# Labels/tooltips for config.EXPERIMENTAL_FEATURES — one entry per key, the
# card build fails loudly on a missing one (gui-smoke catches it).
_EXPERIMENTAL_LABELS = {
    "hdr": lambda: tr("HDR stream"),
    "gamepad_ds5": lambda: tr("DualSense pad (gyro)"),
}
# Optional visible line under a checkbox, for what the tooltip should not be
# the only place for. Unlike the two dicts above, a missing key is fine: no
# entry means the feature needs no qualifier beyond its label.
_EXPERIMENTAL_HINTS = {
    "gamepad_ds5": lambda: tr("sunshine only. For PlayStation controllers."),
}
_EXPERIMENTAL_DETAILS = {
    "hdr": lambda: tr(
        "gamescope --hdr-enabled + DXVK_HDR, on moonshine also its own "
        "compositor. Whether the stream carries HDR is unverified."),
    "gamepad_ds5": lambda: tr(
        "sunshine emulates a DualSense instead of the Xbox pad: gyro and "
        "matching glyphs. Needed for such a client, since sunshine picks "
        "that pad by itself and fails without /dev/uhid. Steam Deck: needs "
        "Steam Input off for moonlight (no trackpad-mouse then). Mounts "
        "the host /dev."),
}


def _build_image(backend: str = backends.DEFAULT) -> str:
    # runtime.build_image stamps the source hash label doctor compares against.
    # Deliberately in-process rather than through the generic shell fix runner:
    # that one shells out to `podstage`, which is not on PATH for the GUI's
    # interpreter, and caps the run at 10 minutes, which a from-scratch
    # moonshine build (it compiles the server and its Rust dependency graph)
    # would blow through.
    runtime.build_image(backend=backend)
    return tr("Image built.")


def _group_label(group: str) -> str:
    if group == doctor.GROUP_HOST:
        return tr("Host")
    if group == doctor.GROUP_STREAMING:
        return tr("Streaming")
    return tr("{name} backend", name=backends.get_or_default(group).label)


def _install_udev_rules() -> str:
    staged = udev.stage()
    rc, out = elevate.run_root(udev.install_shell(staged))
    if rc != 0:
        raise RuntimeError(out)
    return tr("udev rules installed. Input isolation and device access "
              "are set up.")


def _move_home_root(new_root: str) -> str:
    if runtime.is_running():
        raise RuntimeError(tr("Stop the running session before moving sandboxes."))
    old = config.SESSIONS_HOME_ROOT.resolve()
    new = config.set_sessions_home_root(new_root)
    if new == old:
        return tr("Sandbox location unchanged.")
    return tr("Sandboxes moved to {path}.", path=str(new))


def _uninstall(delete_sandboxes: bool, include_shared: bool) -> str:
    results = teardown.remove_user_artifacts(keep_sandboxes=not delete_sandboxes)
    steps = teardown.root_steps(teardown.inventory(), include_shared=include_shared)
    if steps:
        if not elevate.available():
            raise RuntimeError(tr("pkexec is missing — finish with the CLI: "
                                  "podstage uninstall"))
        rc, out = elevate.run_root(" && ".join(steps))
        if rc != 0:
            raise RuntimeError(out)
    left = teardown.leftovers(include_shared=include_shared)
    done = "; ".join(f"{label}: {outcome}" for label, outcome in results)
    if left:
        return tr("Removed ({done}) — still present: {names}", done=done,
                  names=", ".join(a.label for a in left))
    return tr("podstage removed — no residues found. ({done})", done=done)


def _run_fix(fix: str) -> str:
    shell, needs_root = elevate.fix_shell(fix)
    if needs_root:
        rc, out = elevate.run_root(shell)
    else:
        p = subprocess.run(["/bin/sh", "-c", shell], capture_output=True,
                           text=True, timeout=600, check=False)
        rc, out = p.returncode, (p.stdout + p.stderr).strip()
    if rc != 0:
        raise RuntimeError(out or tr("Exit code {rc}", rc=rc))
    return tr("Done.")


class SetupPage(QWidget):
    def __init__(self, ctx) -> None:
        super().__init__()
        self._ctx = ctx
        self._pool: list = []
        self._busy = False
        self._results: list[doctor.CheckResult] = []
        self._update_info: update.UpdateInfo | None = None
        self._build()
        # Re-check when a profile changes, so editing a sandbox on the other
        # page (a different backend, a different port) is reflected here
        # instead of showing a stale verdict until the next Re-check.
        self._config_signature = doctor.config_signature(ctx.config)
        ctx.config_changed.connect(self._on_config_changed)
        self.run_checks()

    # -- layout ----------------------------------------------------------
    def _build(self) -> None:
        # The page grew past one window height — scroll instead of letting
        # the layout crush the check rows to zero.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        frame, lay = card(tr("Preflight checks"))
        header = QHBoxLayout()
        self._recheck_btn = QPushButton(tr("Re-check"))
        self._recheck_btn.clicked.connect(self.run_checks)
        self._headline = QLabel(tr("checking …"))
        self._headline.setProperty("secondary", True)
        header.addWidget(self._headline, 1)
        header.addWidget(self._recheck_btn)
        lay.addLayout(header)

        self._checks_host = QWidget()
        self._checks_box = QVBoxLayout(self._checks_host)
        self._checks_box.setContentsMargins(0, 0, 0, 0)
        self._checks_box.setSpacing(6)
        lay.addWidget(self._checks_host)

        self._action_status = QLabel("")
        self._action_status.setProperty("muted", True)
        self._action_status.setWordWrap(True)
        lay.addWidget(self._action_status)
        root.addWidget(frame)

        hframe, hlay = card(tr("Sandbox location"))
        hexpl = QLabel(tr(
            "Where the sandboxes are stored. Changing this moves the existing "
            "sandboxes."))
        hexpl.setProperty("muted", True)
        hexpl.setWordWrap(True)
        hlay.addWidget(hexpl)
        hrow = QHBoxLayout()
        self._homeroot_label = ElideLabel(str(config.SESSIONS_HOME_ROOT))
        self._homeroot_label.setProperty("mono", True)
        self._homeroot_btn = QPushButton(tr("Change …"))
        self._homeroot_btn.clicked.connect(self._on_change_home_root)
        hrow.addWidget(self._homeroot_label, 1)
        hrow.addWidget(self._homeroot_btn)
        hlay.addLayout(hrow)
        root.addWidget(hframe)

        aframe, alay = card(tr("Desktop integration"))
        self._autostart = QCheckBox(tr("Start the server GUI at login (autostart)"))
        self._autostart.setChecked(desktop.autostart_is_enabled())
        self._autostart.toggled.connect(self._on_autostart_toggled)
        self._menu = QCheckBox(tr("Show in the distribution's application menu"))
        self._menu.setChecked(desktop.menu_is_installed())
        self._menu.toggled.connect(self._on_menu_toggled)
        alay.addWidget(self._autostart)
        alay.addWidget(self._menu)
        root.addWidget(aframe)

        sframe, slay = card(tr("Streaming"))
        self._close_steam = QCheckBox(tr("Close the desktop Steam when a session starts"))
        self._close_steam.setChecked(self._ctx.config.close_desktop_steam)
        self._close_steam.toggled.connect(self._on_close_steam_toggled)
        cshint = QLabel(tr("Off keeps the desktop Steam running; disable its "
                           "\"Guide Button Focuses Steam\", or the session's "
                           "Guide presses open its Big Picture."))
        cshint.setProperty("muted", True)
        cshint.setWordWrap(True)
        slay.addWidget(self._close_steam)
        slay.addWidget(cshint)
        self._keep_preview = QCheckBox(
            tr("Keep the last preview frame during static scenes"))
        self._keep_preview.setToolTip(tr(
            "The capture only delivers frames while the picture changes. Off "
            "hides the preview 45 s after the last new frame."))
        self._keep_preview.setChecked(self._ctx.config.preview_keep_last)
        self._keep_preview.toggled.connect(self._on_keep_preview_toggled)
        slay.addWidget(self._keep_preview)
        self._mouse_kb = QCheckBox(tr("Mouse && keyboard input"))
        self._mouse_kb.setToolTip(tr(
            "Streams the client's mouse and keyboard into the session; games "
            "can lock the pointer for mouse look."))
        self._mouse_kb.setChecked(self._ctx.config.mouse_keyboard)
        self._mouse_kb.toggled.connect(self._on_mouse_kb_toggled)
        mkhint = QLabel(tr("Recommended off for controller-only clients. "
                           "Applies at the next session start."))
        mkhint.setProperty("muted", True)
        mkhint.setWordWrap(True)
        # Its own line, not a tail on the sentence above: the switch gates the
        # virtual mouse/keyboard sunshine creates, while moonshine feeds the
        # client's input straight into its compositor seat and has nothing to
        # switch off. A setting that silently does nothing on one backend has
        # to say so where it is read, not only in the docs.
        mkbackend = QLabel(tr("sunshine only."))
        mkbackend.setProperty("muted", True)
        mkbackend.setWordWrap(True)
        slay.addWidget(self._mouse_kb)
        slay.addWidget(mkhint)
        slay.addWidget(mkbackend)
        self._perf = QCheckBox(tr("Performance metrics (FPS)"))
        self._perf.setToolTip(tr(
            "A probe in the container asks gamescope for the presented frametime of "
            "the running game and shows FPS on the Session page. Works on any GPU "
            "vendor; needs a gamescope with the perf query (3.16+)."))
        self._perf.setChecked(self._ctx.config.perf_metrics)
        self._perf.toggled.connect(self._on_perf_toggled)
        slay.addWidget(self._perf)
        self._guide_hold = QCheckBox(tr("Hold Select to press Guide"))
        self._guide_hold.setToolTip(tr(
            "Hold the controller's Select/Back button for the set time to "
            "press the Guide/Xbox button, which opens the Steam menu (e.g. "
            "to quit a game). For clients that cannot send Guide themselves: "
            "on a Steam Deck the local Steam consumes the button."))
        self._guide_hold.setChecked(self._ctx.config.guide_hold_ms > 0)
        self._guide_hold.toggled.connect(self._on_guide_hold_toggled)
        # 0 in config means off; the spinbox never shows 0 so re-enabling
        # restores the last hold time instead of an invalid value.
        self._guide_hold_ms = QSpinBox()
        self._guide_hold_ms.setRange(200, 10000)
        self._guide_hold_ms.setSingleStep(100)
        self._guide_hold_ms.setSuffix(" ms")
        self._guide_hold_ms.setValue(self._ctx.config.guide_hold_ms or 2000)
        self._guide_hold_ms.setEnabled(self._guide_hold.isChecked())
        self._guide_hold_ms.valueChanged.connect(self._on_guide_hold_ms_changed)
        ghrow = QHBoxLayout()
        ghrow.addWidget(self._guide_hold)
        ghrow.addWidget(self._guide_hold_ms)
        ghrow.addStretch(1)
        ghhint = QLabel(tr("Applies at the next session start."))
        ghhint.setProperty("muted", True)
        ghhint.setWordWrap(True)
        slay.addLayout(ghrow)
        slay.addWidget(ghhint)
        root.addWidget(sframe)

        eframe, elay = card(tr("Experimental features"))
        eexpl = QLabel(tr(
            "Global switches, applied at the next session start. "
            "Container-side features need a current runtime image."))
        eexpl.setProperty("muted", True)
        eexpl.setWordWrap(True)
        elay.addWidget(eexpl)
        for key in config.EXPERIMENTAL_FEATURES:
            box = QCheckBox(_EXPERIMENTAL_LABELS[key]())
            box.setToolTip(_EXPERIMENTAL_DETAILS[key]())
            box.setChecked(self._ctx.config.experimental.get(key, False))
            box.toggled.connect(
                lambda on, k=key: self._on_experimental_toggled(k, on))
            elay.addWidget(box)
            if key in _EXPERIMENTAL_HINTS:
                hint = QLabel(_EXPERIMENTAL_HINTS[key]())
                hint.setProperty("muted", True)
                hint.setWordWrap(True)
                hint.setContentsMargins(22, 0, 0, 6)  # under the box label
                elay.addWidget(hint)
        root.addWidget(eframe)

        lframe, llay = card(tr("Language"))
        lrow = QHBoxLayout()
        self._lang = QComboBox()
        for label, code in ((tr("Automatic (system)"), "auto"),
                            ("English", "en"), ("Deutsch", "de")):
            self._lang.addItem(label, code)
        idx = self._lang.findData(self._ctx.config.language)
        self._lang.setCurrentIndex(max(idx, 0))
        self._lang.currentIndexChanged.connect(self._on_language_changed)
        lhint = QLabel(tr("Applies after restarting the GUI."))
        lhint.setProperty("muted", True)
        lrow.addWidget(self._lang)
        lrow.addWidget(lhint, 1)
        llay.addLayout(lrow)
        root.addWidget(lframe)

        upframe, uplay = card(tr("Updates"))
        upexpl = QLabel(tr(
            "Checks the GitHub releases for a newer version."))
        upexpl.setProperty("muted", True)
        upexpl.setWordWrap(True)
        uplay.addWidget(upexpl)
        uprow = QHBoxLayout()
        self._update_status = QLabel(tr("Installed: {current}", current=__version__))
        self._update_status.setProperty("muted", True)
        self._update_status.setWordWrap(True)
        self._update_btn = QPushButton(tr("Check for updates"))
        self._update_btn.clicked.connect(self._on_check_updates)
        self._release_btn = QPushButton(tr("Open release page"))
        self._release_btn.setVisible(False)
        self._release_btn.clicked.connect(self._on_open_release)
        uprow.addWidget(self._update_status, 1)
        uprow.addWidget(self._release_btn)
        uprow.addWidget(self._update_btn)
        uplay.addLayout(uprow)
        root.addWidget(upframe)

        uframe, ulay = card(tr("Remove podstage"))
        uexpl = QLabel(tr("Removes the udev rules, firewall ports, runtime "
                          "image, data and configuration. Shared pieces stay "
                          "unless selected."))
        uexpl.setProperty("muted", True)
        uexpl.setWordWrap(True)
        ulay.addWidget(uexpl)
        self._rm_sandboxes = QCheckBox(tr("Also delete sandboxes (Steam logins, saves)"))
        self._rm_sandboxes.setChecked(True)
        self._rm_shared = QCheckBox(tr("Also remove shared pieces (mDNS service, NVIDIA CDI spec)"))
        ulay.addWidget(self._rm_sandboxes)
        ulay.addWidget(self._rm_shared)
        urow = QHBoxLayout()
        self._uninstall_btn = QPushButton(tr("Uninstall …"))
        self._uninstall_btn.clicked.connect(self._on_uninstall_clicked)
        urow.addStretch(1)
        urow.addWidget(self._uninstall_btn)
        ulay.addLayout(urow)
        root.addWidget(uframe)

        if not elevate.available():
            warn = QLabel(tr("pkexec is missing, so there is no graphical "
                             "privilege elevation. Run fixes manually via "
                             "sudo (podstage setup)."))
            warn.setProperty("status", "warn")
            warn.setWordWrap(True)
            root.addWidget(warn)
        root.addStretch(1)

    # -- checks ----------------------------------------------------------
    def _on_config_changed(self) -> None:
        """Re-check only when a config change can actually change a result.

        This page saves on every toggle it owns (language, preview behaviour,
        mouse & keyboard), and the session page saves on every quality
        dropdown. Re-running the checks on each of those would fire a
        container probe per keystroke-ish event for no gain, so compare the
        few fields the checks read instead."""
        signature = doctor.config_signature(self._ctx.config)
        if signature == self._config_signature:
            return
        self._config_signature = signature
        self.run_checks()

    def run_checks(self) -> None:
        if self._busy:
            return
        self._headline.setText(tr("checking …"))
        self._recheck_btn.setEnabled(False)

        def _collect() -> str:
            self._results = doctor.run_all()
            return "checked"

        start_action(self._pool, _collect, "Checks", self._on_checked)

    def _on_checked(self, ok: bool, msg: str) -> None:
        self._recheck_btn.setEnabled(True)
        if not ok:
            self._headline.setText(tr("Check failed: {msg}", msg=msg))
            return
        self._render_results()

    def _render_results(self) -> None:
        while self._checks_box.count():
            item = self._checks_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        fails = sum(r.status is doctor.Status.FAIL for r in self._results)
        warns = sum(r.status is doctor.Status.WARN for r in self._results)
        if fails:
            self._headline.setText(tr(
                "{fails} blocker(s), {warns} warning(s). Fix top to bottom.",
                fails=fails, warns=warns))
        elif warns:
            self._headline.setText(tr("Ready, {warns} warning(s).", warns=warns))
        else:
            self._headline.setText(tr("All set ✓"))
        # Grouped, but still one list on one page: the headline above counts
        # across every group, so a failure can never hide behind a heading the
        # way it would behind a tab. Every backend gets a group whether a
        # profile uses it or not; being unused only lowers the severity to
        # INFO, so the row states its gap without turning the summary red
        # (doctor.run_all).
        for group, rows in doctor.by_group(self._results):
            self._checks_box.addWidget(self._group_heading(_group_label(group)))
            for r in rows:
                self._checks_box.addWidget(self._check_row(r))

        self._homeroot_label.setText(str(config.SESSIONS_HOME_ROOT))

    def _group_heading(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setProperty("groupTitle", True)
        label.setContentsMargins(0, 6, 0, 0)
        return label

    def _check_row(self, r: doctor.CheckResult) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        # Indented under its group heading, so the grouping reads as structure
        # and not as an unrelated label dropped between rows.
        h.setContentsMargins(10, 0, 0, 0)
        h.setSpacing(8)
        glyph_text, status = _GLYPH[r.status]
        glyph = QLabel(glyph_text)
        glyph.setProperty("status", status)
        glyph.setFixedWidth(14)
        name = QLabel(r.name)
        name.setFixedWidth(120)
        detail = ElideLabel(r.detail)
        detail.setProperty("muted", True)
        h.addWidget(glyph)
        h.addWidget(name)
        h.addWidget(detail, 1)
        button = self._fix_button(r)
        if button is not None:
            h.addWidget(button)
        return row

    def _fix_button(self, r: doctor.CheckResult) -> QPushButton | None:
        if r.status is doctor.Status.OK:
            return None
        if r.name in ("image", "moonshine image"):
            # Also at INFO (an unused backend's image): building is
            # preparation, not repair, and that image is the one you build
            # before switching a profile to it. doctor omits the fix string
            # there so `podstage setup` stays quiet about it.
            backend = (backends.MOONSHINE.name if r.name.startswith("moonshine")
                       else backends.SUNSHINE.name)
            btn = QPushButton(tr("Build image"))
            btn.clicked.connect(
                lambda: self._start("Image-Build",
                                    lambda: _build_image(backend)))
        elif r.status is doctor.Status.INFO:
            return None  # a path this install does not take, nothing to press
        elif r.name == "udev rules":
            # The generated per-user OWNER rule must be staged first — the
            # generic fix runner can't do that, so this button wraps
            # stage + pkexec install in one action.
            btn = QPushButton(tr("Install (pkexec)"))
            btn.clicked.connect(lambda: self._start("udev", _install_udev_rules))
        elif r.fix:
            _, needs_root = elevate.fix_shell(r.fix)
            btn = QPushButton(tr("Fix (pkexec)") if needs_root else tr("Fix"))
            fix = r.fix
            btn.clicked.connect(lambda: self._start(r.name, lambda: _run_fix(fix)))
        else:
            return None
        # The pkexec-availability gate keys off the literal "pkexec" tag, which
        # every translation of these labels keeps verbatim (it is a command).
        if "pkexec" in btn.text() and not elevate.available():
            btn.setEnabled(False)
        btn.setEnabled(btn.isEnabled() and not self._busy)
        return btn

    def _on_language_changed(self, _index: int) -> None:
        self._ctx.config.language = self._lang.currentData()
        self._ctx.save()
        self._action_status.setText(tr("Language saved. Restart the GUI to apply."))

    def _on_close_steam_toggled(self, enabled: bool) -> None:
        self._ctx.config.close_desktop_steam = enabled
        self._ctx.save()

    def _on_keep_preview_toggled(self, enabled: bool) -> None:
        self._ctx.config.preview_keep_last = enabled
        self._ctx.save()

    def _on_mouse_kb_toggled(self, enabled: bool) -> None:
        self._ctx.config.mouse_keyboard = enabled
        self._ctx.save()

    def _on_perf_toggled(self, enabled: bool) -> None:
        self._ctx.config.perf_metrics = enabled
        self._ctx.save()

    def _on_guide_hold_toggled(self, enabled: bool) -> None:
        self._guide_hold_ms.setEnabled(enabled)
        self._ctx.config.guide_hold_ms = (
            self._guide_hold_ms.value() if enabled else 0)
        self._ctx.save()

    def _on_guide_hold_ms_changed(self, value: int) -> None:
        # Only while enabled: the disabled spinbox keeps its value as the
        # restore point, config stays 0.
        if self._guide_hold.isChecked():
            self._ctx.config.guide_hold_ms = value
            self._ctx.save()

    def _on_experimental_toggled(self, key: str, enabled: bool) -> None:
        self._ctx.config.experimental[key] = enabled
        self._ctx.save()
        self._action_status.setText(
            tr("Experimental features apply from the next session start."))

    def _on_change_home_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("Choose a folder for the sandbox homes"),
            str(config.SESSIONS_HOME_ROOT))
        if chosen:
            self._start("Sandbox", lambda: _move_home_root(chosen))

    def _on_uninstall_clicked(self) -> None:
        present = [a for a in teardown.inventory() if a.present]
        if not present:
            self._action_status.setText(tr("Nothing to remove."))
            return
        lines = "\n".join(
            f"• {a.label}" + (f" — {a.detail}" if a.detail else "")
            + ("  " + tr("(shared — kept)")
               if a.shared and not self._rm_shared.isChecked() else "")
            for a in present)
        answer = QMessageBox.question(
            self, tr("Remove podstage?"),
            tr("This removes:") + f"\n\n{lines}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_sandboxes = self._rm_sandboxes.isChecked()
        include_shared = self._rm_shared.isChecked()
        self._start("Uninstall",
                    lambda: _uninstall(delete_sandboxes, include_shared))

    def _on_autostart_toggled(self, enabled: bool) -> None:
        try:
            desktop.autostart_enable() if enabled else desktop.autostart_disable()
            self._action_status.setText(
                tr("Autostart enabled. The GUI starts at the next login.")
                if enabled else tr("Autostart disabled."))
        except (OSError, RuntimeError) as e:
            self._action_status.setText(tr("Autostart: {e}", e=e))
            self._reset_check(self._autostart, desktop.autostart_is_enabled())

    def _on_menu_toggled(self, enabled: bool) -> None:
        try:
            desktop.menu_install() if enabled else desktop.menu_remove()
            self._action_status.setText(
                tr("Added to the application menu.") if enabled
                else tr("Removed from the application menu."))
        except (OSError, RuntimeError) as e:
            self._action_status.setText(tr("Application menu: {e}", e=e))
            self._reset_check(self._menu, desktop.menu_is_installed())

    @staticmethod
    def _reset_check(box: QCheckBox, state: bool) -> None:
        box.blockSignals(True)
        box.setChecked(state)
        box.blockSignals(False)

    # -- update check ----------------------------------------------------
    def _on_check_updates(self) -> None:
        self._update_btn.setEnabled(False)
        self._release_btn.setVisible(False)
        self._update_status.setText(tr("checking …"))

        def _check() -> str:
            info = update.check_latest()
            self._update_info = info  # read back on the UI thread in _done
            if not info.is_newer:
                return tr("podstage {current} is up to date.", current=info.current)
            msg = tr("Version {latest} is available (installed: {current}).",
                     latest=info.latest, current=info.current)
            if info.mentions_image_rebuild:
                msg += " " + tr("The release notes mention an image rebuild.")
            return msg

        start_action(self._pool, _check, "Update check", self._on_update_checked)

    def _on_update_checked(self, ok: bool, msg: str) -> None:
        self._update_btn.setEnabled(True)
        self._update_status.setText(
            msg if ok else tr("Update check failed: {msg}", msg=msg))
        info = self._update_info
        self._release_btn.setVisible(ok and info is not None and info.is_newer)

    def _on_open_release(self) -> None:
        info = self._update_info
        QDesktopServices.openUrl(QUrl(info.url if info else update.RELEASES_URL))

    # -- actions ---------------------------------------------------------
    def _start(self, label: str, fn) -> None:
        if self._busy:
            return
        self._busy = True
        self._action_status.setText(tr("{label} running …", label=label))
        self._render_results()  # grey out buttons

        def _done(ok: bool, msg: str) -> None:
            self._busy = False
            self._action_status.setText(msg if ok else f"{label}: {msg}")
            self.run_checks()

        start_action(self._pool, fn, label, _done)
