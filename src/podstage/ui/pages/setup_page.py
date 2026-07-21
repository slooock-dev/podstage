"""Setup page — doctor checks with one-click fixes.

Every root-gated fix runs through pkexec (graphical polkit password dialog) —
no copy/paste sudo. After each action the checks re-run automatically. The
goal: complete first-time setup by clicking top to bottom, then never see a
password again — the runtime container is rootless, so the udev rules install
here is the only root interaction podstage ever needs.

Doctor check names and details are shown verbatim: they are English technical
diagnostics shared with the CLI and are intentionally not translated.
"""

from __future__ import annotations

import subprocess

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ... import config
from ...core import desktop, doctor, elevate, runtime, udev
from ..i18n import tr
from ..widgets import ElideLabel, card
from ..workers import start_action

_GLYPH = {doctor.Status.OK: ("●", "ok"),
          doctor.Status.WARN: ("▲", "warn"),
          doctor.Status.FAIL: ("✖", "fail")}


def _build_image() -> str:
    p = subprocess.run(
        ["podman", "build", "-t", runtime.DEFAULT_IMAGE, "containers/runtime/"],
        cwd=doctor.REPO_ROOT, capture_output=True, text=True, timeout=3600)
    if p.returncode != 0:
        tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-8:])
        raise RuntimeError(tr("podman build failed:\n{tail}", tail=tail))
    return tr("Image built.")


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


def _run_fix(fix: str) -> str:
    shell, needs_root = elevate.fix_shell(fix)
    if needs_root:
        rc, out = elevate.run_root(shell)
    else:
        p = subprocess.run(["/bin/sh", "-c", shell], capture_output=True,
                           text=True, timeout=600)
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
        self._build()
        self.run_checks()

    # -- layout ----------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
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
        cshint = QLabel(tr("Off doesn't close the desktop Steam when a session "
                           "starts."))
        cshint.setProperty("muted", True)
        cshint.setWordWrap(True)
        slay.addWidget(self._close_steam)
        slay.addWidget(cshint)
        root.addWidget(sframe)

        lframe, llay = card(tr("Language"))
        lrow = QHBoxLayout()
        self._lang = QComboBox()
        for label, code in ((tr("Automatic (system)"), "auto"),
                            ("English", "en"), ("Deutsch", "de")):
            self._lang.addItem(label, code)
        idx = self._lang.findData(self._ctx.config.language)
        self._lang.setCurrentIndex(idx if idx >= 0 else 0)
        self._lang.currentIndexChanged.connect(self._on_language_changed)
        lhint = QLabel(tr("Applies after restarting the GUI."))
        lhint.setProperty("muted", True)
        lrow.addWidget(self._lang)
        lrow.addWidget(lhint, 1)
        llay.addLayout(lrow)
        root.addWidget(lframe)

        if not elevate.available():
            warn = QLabel(tr("pkexec is missing, so there is no graphical "
                             "privilege elevation. Run fixes manually via "
                             "sudo (podstage setup)."))
            warn.setProperty("status", "warn")
            warn.setWordWrap(True)
            root.addWidget(warn)
        root.addStretch(1)

    # -- checks ----------------------------------------------------------
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
        for r in self._results:
            self._checks_box.addWidget(self._check_row(r))

        self._homeroot_label.setText(str(config.SESSIONS_HOME_ROOT))

    def _check_row(self, r: doctor.CheckResult) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
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
        if r.name == "image":
            btn = QPushButton(tr("Build image"))
            btn.clicked.connect(lambda: self._start("Image-Build", _build_image))
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

    def _on_change_home_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("Choose a folder for the sandbox homes"),
            str(config.SESSIONS_HOME_ROOT))
        if chosen:
            self._start("Sandbox", lambda: _move_home_root(chosen))

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
