"""Sandboxen page — client profiles and their isolated Steam HOMEs.

Create/edit/delete profiles (config.toml), bootstrap a sandbox by running the
isolated Steam visibly for first-time login, and show per-sandbox state:
logged in, paired Moonlight clients, disk usage.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...core import provisioner, runtime, sandbox
from ...core.session import Session
from ..i18n import tr
from ..widgets import card
from ..workers import start_action

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _fmt_size(size: int | None) -> str:
    if size is None:
        return "—"
    gib = size / (1 << 30)
    return f"{gib:.1f} GiB" if gib >= 1 else f"{size / (1 << 20):.0f} MiB"


class ProfileDialog(QDialog):
    """Create or edit one client profile."""

    def __init__(self, parent, cfg: config.AppConfig,
                 existing: config.SessionConfig | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._existing = existing
        self.result_profile: config.SessionConfig | None = None
        self.setWindowTitle(tr("Edit profile") if existing else tr("New profile"))
        self.setMinimumWidth(480)
        # Translated combo labels that double as sentinels (compared by identity
        # below, never by a literal string): "custom" for a typed WxH@R, and
        # "Pick at startup" for the resolution-at-start ("ask") profile.
        self._custom_label = tr("custom")
        self._pick_label = tr("Pick at startup")

        form = QFormLayout(self)
        form.setSpacing(8)
        self._name = QLineEdit(existing.name if existing else "")
        self._name.setEnabled(existing is None)
        self._name.setPlaceholderText(tr("e.g. deck, laptop, livingroom"))
        form.addRow(tr("Name"), self._name)

        self._resolution = QComboBox()
        self._resolution.addItems(
            [*config.RESOLUTION_PRESETS.keys(), self._pick_label, self._custom_label])
        self._custom = QLineEdit()
        self._custom.setPlaceholderText(tr("WidthxHeight@Hz, e.g. 1920x1080@60"))
        current = existing.resolution if existing else "deck"
        if current in config.RESOLUTION_PRESETS:
            self._resolution.setCurrentText(current)
        elif current == "ask":
            self._resolution.setCurrentText(self._pick_label)
        else:
            self._resolution.setCurrentText(self._custom_label)
            self._custom.setText(current)
        self._resolution.currentTextChanged.connect(self._sync_custom)
        form.addRow(tr("Resolution"), self._resolution)
        form.addRow("", self._custom)
        self._sync_custom(self._resolution.currentText())

        self._port = QSpinBox()
        self._port.setRange(1024, 64000)
        self._port.setValue(existing.sunshine_port_base if existing else 47989)
        form.addRow(tr("Sunshine port"), self._port)

        form.addRow(self._build_games(existing))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _sync_custom(self, choice: str) -> None:
        self._custom.setVisible(choice == self._custom_label)

    def _build_games(self, existing) -> QWidget:
        """A self-contained games picker: an 'all' toggle above a filterable,
        checkable list of installed games (clear name + AppID). Fewer games =
        a smaller sandbox (each game gets its own Proton prefix + shader cache)."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        v.addWidget(QLabel(tr("Games in this sandbox")))

        self._all_games = QCheckBox(
            tr("Include every installed game (and any you add later)"))
        self._all_games.toggled.connect(self._on_all_games_toggled)
        v.addWidget(self._all_games)

        self._game_filter = QLineEdit()
        self._game_filter.setPlaceholderText(tr("Filter games …"))
        self._game_filter.textChanged.connect(self._filter_games)
        v.addWidget(self._game_filter)

        self._game_list = QListWidget()
        self._game_list.setMinimumHeight(200)
        try:
            self._games = provisioner.installed_games()
        except Exception:  # noqa: BLE001 — dialog must open even if Steam is unreadable
            self._games = []
        selected = set(existing.app_ids) if existing else set()
        for app_id, name in self._games:
            item = QListWidgetItem(f"{name}   ({app_id})")
            item.setData(Qt.ItemDataRole.UserRole, app_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked
                               if (not selected or app_id in selected)
                               else Qt.CheckState.Unchecked)
            self._game_list.addItem(item)
        self._game_list.itemChanged.connect(self._on_item_changed)
        v.addWidget(self._game_list)

        self._game_count = QLabel()
        self._game_count.setProperty("muted", True)
        self._game_count.setWordWrap(True)
        v.addWidget(self._game_count)

        if not self._games:
            self._all_games.setEnabled(False)
            self._game_list.setEnabled(False)
            self._game_count.setText(tr("No installed games found. Log in to the "
                                        "sandbox's Steam first."))
        # New profile or empty app_ids → "all"; an explicit subset otherwise.
        self._all_games.setChecked(not existing or not existing.app_ids)
        self._on_all_games_toggled(self._all_games.isChecked())
        return box

    def _on_all_games_toggled(self, all_on: bool) -> None:
        # The list always stays enabled so it can be scrolled and browsed;
        # turning "all" on just (re)checks every game.
        if all_on and self._games:
            self._game_list.blockSignals(True)
            for i in range(self._game_list.count()):
                self._game_list.item(i).setCheckState(Qt.CheckState.Checked)
            self._game_list.blockSignals(False)
        self._update_game_count()

    def _on_item_changed(self, _item) -> None:
        # Touching a game means the user wants a custom set → leave "all" mode.
        if self._all_games.isChecked():
            self._all_games.blockSignals(True)
            self._all_games.setChecked(False)
            self._all_games.blockSignals(False)
        self._update_game_count()

    def _filter_games(self, text: str) -> None:
        needle = text.lower()
        for i in range(self._game_list.count()):
            item = self._game_list.item(i)
            item.setHidden(needle not in item.text().lower())

    def _update_game_count(self, *_a) -> None:
        if not self._games:
            return
        total = len(self._games)
        if self._all_games.isChecked():
            self._game_count.setText(tr("All {total} games included.", total=total))
        else:
            n = sum(self._game_list.item(i).checkState() == Qt.CheckState.Checked
                    for i in range(self._game_list.count()))
            self._game_count.setText(
                tr("{n} of {total} games selected.", n=n, total=total))

    def _on_accept(self) -> None:
        name = self._name.text().strip()
        if not _NAME_RE.match(name):
            QMessageBox.warning(self, tr("Invalid name"),
                                tr("Only letters, digits, '-' and '_' are allowed."))
            return
        if self._existing is None and self._cfg.get(name) is not None:
            QMessageBox.warning(self, tr("Name taken"),
                                tr("A profile '{name}' already exists.", name=name))
            return
        resolution = self._resolution.currentText()
        if resolution == self._pick_label:
            resolution = "ask"
        elif resolution == self._custom_label:
            resolution = self._custom.text().strip()
            try:
                config.parse_dimensions(resolution)
            except (ValueError, TypeError):
                QMessageBox.warning(self, tr("Invalid resolution"),
                                    tr("Format: WidthxHeight@Hz, e.g. 1920x1080@60"))
                return
        if self._all_games.isChecked() or not self._games:
            app_ids: list[int] = []
        else:
            app_ids = [self._game_list.item(i).data(Qt.ItemDataRole.UserRole)
                       for i in range(self._game_list.count())
                       if self._game_list.item(i).checkState() == Qt.CheckState.Checked]
        port = self._port.value()
        clash = next((s for s in self._cfg.sessions
                      if s.sunshine_port_base == port and s.name != name), None)
        if clash is not None:
            QMessageBox.warning(self, tr("Port in use"),
                                tr("Port {port} is already used by profile '{name}'.",
                                   port=port, name=clash.name))
            return
        base = self._existing or config.SessionConfig(name=name)
        self.result_profile = config.SessionConfig(
            name=name, resolution=resolution, app_ids=app_ids,
            sunshine_port_base=port, home=base.home,
            sunshine_extra=dict(base.sunshine_extra),
        )
        self.accept()


class DeleteDialog(QDialog):
    """Delete a profile — optionally including the sandbox data (gigabytes!)."""

    def __init__(self, parent, name: str, home, size: int | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Delete '{name}'", name=name))
        self.delete_data = False
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        self._profile_only = QRadioButton(
            tr("Remove only the profile (keep sandbox data)"))
        self._profile_only.setChecked(True)
        self._with_data = QRadioButton(
            tr("Delete profile AND sandbox data: {home} ({size})",
               home=home, size=_fmt_size(size)))
        lay.addWidget(self._profile_only)
        lay.addWidget(self._with_data)

        self._confirm = QLineEdit()
        self._confirm.setPlaceholderText(tr("Type '{name}' to confirm", name=name))
        self._confirm.setVisible(False)
        lay.addWidget(self._confirm)

        warn = QLabel(tr("The sandbox holds a logged-in Steam account, settings "
                         "and save games for this client."))
        warn.setProperty("muted", True)
        warn.setWordWrap(True)
        lay.addWidget(warn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        def _update() -> None:
            with_data = self._with_data.isChecked()
            self._confirm.setVisible(with_data)
            self._ok.setEnabled(not with_data or self._confirm.text() == name)
            self.delete_data = with_data

        self._with_data.toggled.connect(_update)
        self._confirm.textChanged.connect(_update)
        _update()


class SandboxPage(QWidget):
    def __init__(self, ctx) -> None:
        super().__init__()
        self._ctx = ctx
        self._pool: list = []
        self._steam_proc: QProcess | None = None
        self._bootstrap_profile: str | None = None
        self._sizes: dict[str, int | None] = {}
        self._build()
        ctx.config_changed.connect(self.refresh)
        self.refresh()

    # -- layout ----------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        frame, lay = card(tr("Client sandboxes"))
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            [tr("Name"), tr("Resolution"), tr("Port"), tr("Login"),
             tr("Pairings"), tr("Size")])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(160)
        self._table.itemSelectionChanged.connect(self._update_login_btn)
        lay.addWidget(self._table)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        new_btn = QPushButton(tr("New …"))
        new_btn.clicked.connect(self._on_new)
        edit_btn = QPushButton(tr("Edit …"))
        edit_btn.clicked.connect(self._on_edit)
        self._delete_btn = QPushButton(tr("Delete …"))
        self._delete_btn.setProperty("danger", True)
        self._delete_btn.clicked.connect(self._on_delete)
        self._login_btn = QPushButton(tr("Start Steam login"))
        self._login_btn.setProperty("primary", True)
        self._login_btn.clicked.connect(self._on_bootstrap)
        buttons.addWidget(new_btn)
        buttons.addWidget(edit_btn)
        buttons.addWidget(self._delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._login_btn)
        lay.addLayout(buttons)

        self._status = QLabel("")
        self._status.setProperty("muted", True)
        self._status.setWordWrap(True)
        lay.addWidget(self._status)
        root.addWidget(frame)

        hint = QLabel(tr(
            "Setup: 'Start Steam login' opens the isolated Steam visibly on the "
            "desktop. Log in there (Steam Guard), then close Steam; the game "
            "library is provisioned automatically."))
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)

    # -- table -----------------------------------------------------------
    def _selected(self) -> config.SessionConfig | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        return self._ctx.config.get(self._table.item(row, 0).text())

    def refresh(self) -> None:
        selected = self._table.currentRow()
        sessions = self._ctx.config.sessions
        self._table.setRowCount(len(sessions))
        for row, sc in enumerate(sessions):
            info = sandbox.inspect(sc)
            resolution = tr("Pick at startup") if sc.is_dynamic() else sc.resolution
            login = tr("✓ logged in") if info.logged_in else (
                tr("— empty") if not info.exists else tr("✗ no login"))
            paired = ", ".join(info.paired) if info.paired else "—"
            values = [sc.name, resolution, str(sc.sunshine_port_base), login,
                      paired, _fmt_size(self._sizes.get(sc.name))]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (2, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()
        for col in range(self._table.columnCount() - 1):
            # the stylesheet's item padding is not part of the size hint
            self._table.setColumnWidth(col, self._table.columnWidth(col) + 20)
        if 0 <= selected < len(sessions):
            self._table.selectRow(selected)
        self._update_login_btn()
        self._refresh_sizes()

    def _update_login_btn(self) -> None:
        """'Start Steam login' until the selected sandbox is logged in; after
        that the same button opens the sandbox Steam for settings/Proton."""
        sc = self._selected()
        logged_in = sc is not None and sandbox.steam_logged_in(sc.home_dir())
        self._login_btn.setText(tr("Open sandbox Steam") if logged_in
                                else tr("Start Steam login"))

    def _refresh_sizes(self) -> None:
        profiles = [(sc.name, sc.home_dir()) for sc in self._ctx.config.sessions
                    if sc.name not in self._sizes and sc.home_dir().is_dir()]
        if not profiles:
            return

        def _measure() -> str:
            for name, home in profiles:
                self._sizes[name] = sandbox.size_bytes(home)
            return "sizes"

        start_action(self._pool, _measure, "Sizes", self._on_sizes_done)

    def _on_sizes_done(self, ok: bool, _msg: str) -> None:
        if ok:
            for row in range(self._table.rowCount()):
                name = self._table.item(row, 0).text()
                self._table.item(row, 5).setText(_fmt_size(self._sizes.get(name)))

    # -- profile CRUD ----------------------------------------------------
    def _on_new(self) -> None:
        dlg = ProfileDialog(self, self._ctx.config)
        if dlg.exec() and dlg.result_profile:
            self._ctx.config.upsert(dlg.result_profile)
            self._ctx.save()
            self._status.setText(tr(
                "Profile '{name}' created. Now use 'Start Steam login' to set "
                "it up.", name=dlg.result_profile.name))

    def _on_edit(self) -> None:
        sc = self._selected()
        if sc is None:
            self._status.setText(tr("No profile selected."))
            return
        dlg = ProfileDialog(self, self._ctx.config, existing=sc)
        if dlg.exec() and dlg.result_profile:
            self._ctx.config.upsert(dlg.result_profile)
            self._ctx.save()
            self._status.setText(tr("Profile '{name}' saved.", name=sc.name))

    def _on_delete(self) -> None:
        sc = self._selected()
        if sc is None:
            self._status.setText(tr("No profile selected."))
            return
        st = runtime.status()
        if st.running and st.client in (None, "", sc.name):
            self._status.setText(tr("Stop the running session first."))
            return
        home = sc.home_dir()
        dlg = DeleteDialog(self, sc.name, home, self._sizes.get(sc.name))
        if not dlg.exec():
            return
        self._ctx.config.remove(sc.name)
        self._ctx.save()
        self._sizes.pop(sc.name, None)
        if dlg.delete_data and home.exists():
            self._status.setText(tr("Deleting {home} …", home=home))
            self._delete_btn.setEnabled(False)

            def _delete() -> str:
                sandbox.delete(home)
                return tr("Deleted profile and sandbox data of '{name}'.", name=sc.name)

            start_action(self._pool, _delete, "Delete", self._on_delete_done)
        else:
            self._status.setText(tr(
                "Profile '{name}' removed (sandbox data kept at {home}).",
                name=sc.name, home=home))

    def _on_delete_done(self, ok: bool, msg: str) -> None:
        self._delete_btn.setEnabled(True)
        self._status.setText(msg if ok else tr("Error: {msg}", msg=msg))
        self.refresh()

    # -- bootstrap (first-time Steam login) ------------------------------
    def _on_bootstrap(self) -> None:
        sc = self._selected()
        if sc is None:
            self._status.setText(tr("No profile selected."))
            return
        if self._steam_proc is not None:
            self._status.setText(tr("A Steam login is already running."))
            return
        if runtime.status().running:
            self._status.setText(tr("Stop the running streaming session first; "
                                    "Steam can only run once."))
            return
        if self._ctx.config.close_desktop_steam:
            body = tr("Steam will now start visibly with the isolated sandbox\n{home}\n"
                      "Any running desktop Steam will be closed.\n\n"
                      "Log in there (confirm Steam Guard), then close Steam.\n"
                      "Continue?", home=sc.home_dir())
        else:
            body = tr("Steam will now start visibly with the isolated sandbox\n{home}\n\n"
                      "Log in there (confirm Steam Guard), then close Steam.\n"
                      "Continue?", home=sc.home_dir())
        answer = QMessageBox.question(self, tr("Steam login"), body)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._bootstrap_profile = sc.name
        self._login_btn.setEnabled(False)
        self._status.setText(tr("Closing desktop Steam …")
                             if self._ctx.config.close_desktop_steam
                             else tr("Preparing sandbox …"))
        session = Session(sc)

        def _prepare() -> str:
            session.home.mkdir(parents=True, exist_ok=True)
            session.close_host_steam()
            return "prepared"

        start_action(self._pool, _prepare, "Prepare", self._on_prepared)

    def _on_prepared(self, ok: bool, msg: str) -> None:
        sc = self._ctx.config.get(self._bootstrap_profile or "")
        if not ok or sc is None:
            self._finish_bootstrap(tr("Preparation failed: {msg}", msg=msg))
            return
        env = QProcessEnvironment.systemEnvironment()
        env.insert("HOME", str(sc.home_dir()))
        self._steam_proc = QProcess(self)
        self._steam_proc.setProcessEnvironment(env)
        self._steam_proc.finished.connect(self._on_steam_finished)
        self._steam_proc.errorOccurred.connect(self._on_steam_error)
        self._steam_proc.start("steam", [])
        self._status.setText(tr(
            "Steam is running isolated for '{name}'. Log in, then close "
            "Steam (Steam → Exit).", name=sc.name))

    def _on_steam_error(self, _error) -> None:
        if self._steam_proc is not None and \
                self._steam_proc.state() == QProcess.ProcessState.NotRunning:
            self._steam_proc = None
            self._finish_bootstrap(tr("Steam could not be started. Is it installed?"))

    def _on_steam_finished(self, _code: int, _status) -> None:
        self._steam_proc = None
        sc = self._ctx.config.get(self._bootstrap_profile or "")
        if sc is None:
            self._finish_bootstrap(tr("Profile vanished; nothing was provisioned."))
            return
        session = Session(sc)
        if not session.is_bootstrapped():
            self._finish_bootstrap(tr("Steam exited but no login was found. Try "
                                      "'Start Steam login' again."))
            return
        self._status.setText(tr("Login detected, provisioning the game library …"))

        def _provision() -> str:
            session.provision_apps()
            return tr("'{name}' is set up. Start the session on the "
                      "'Session' page.", name=sc.name)

        start_action(self._pool, _provision, "Provision", self._on_provisioned)

    def _on_provisioned(self, ok: bool, msg: str) -> None:
        self._finish_bootstrap(msg if ok else tr("Provisioning failed: {msg}", msg=msg))

    def _finish_bootstrap(self, msg: str) -> None:
        self._bootstrap_profile = None
        self._login_btn.setEnabled(True)
        self._status.setText(msg)
        self.refresh()
