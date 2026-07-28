"""Session page — start/stop the stream, live telemetry, stream quality.

The page renders explicit states: stopped → starting… → running (client) →
stopping…, plus an error state with the failure message. Start/stop run on
worker threads; telemetry snapshots arrive from the app-owned PollWorker.
"""

import os
import time

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...core import backends, monitor, moonshine_api, runtime, sandbox, sunshine_api
from ...core.session import Session
from .. import theme
from ..i18n import tr
from ..widgets import AspectPixmapLabel, InfoRow, Meter, align_captions, card
from ..workers import start_action

try:  # fallback reference for the RAM meter when /proc/meminfo is unreadable
    _RAM_TOTAL_MB = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) >> 20
except (ValueError, OSError):
    _RAM_TOTAL_MB = 0

# Sunshine NVENC quality knobs (sunshine.conf value → translated label builder).
# Built inside the widget so tr() resolves after the language is set.
_PRESET_LABELS = {
    "1": lambda: tr("fastest encoding (default)"), "2": lambda: tr("faster"),
    "3": lambda: tr("fast"), "4": lambda: tr("balanced"), "5": lambda: tr("slow"),
    "6": lambda: tr("slower"), "7": lambda: tr("best quality"),
}
_TWOPASS_LABELS = {
    "disabled": lambda: tr("off"),
    "quarter_res": lambda: tr("quarter resolution (default)"),
    "full_res": lambda: tr("full resolution"),
}
# Sunshine VAAPI quality knobs (AMD path). Values verified against Sunshine's
# configuration docs (vaapi_quality / vaapi_rc / vaapi_strict_rc_buffer).
_VAAPI_QUALITY_LABELS = {
    "auto": lambda: tr("auto (default)"), "speed": lambda: tr("speed"),
    "balanced": lambda: tr("balanced"), "quality": lambda: tr("quality"),
}
_VAAPI_RC_LABELS = {
    "auto": lambda: tr("auto (default)"),
    "vbr": lambda: tr("variable bitrate"),
    "cbr": lambda: tr("constant bitrate"),
    "cqp": lambda: tr("constant quality (QP)"),
    "icq": lambda: tr("intelligent constant quality"),
    "qvbr": lambda: tr("quality-defined VBR"),
    "avbr": lambda: tr("average VBR"),
}


THUMB_MAX_AGE_S = 45  # strict mode only: older previews count as stale


class PairDialog(QDialog):
    """Submit the PIN Moonlight shows to pair a new client."""

    def __init__(self, parent, default_name: str, advertised: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Pair client"))
        self.setMinimumWidth(320)
        form = QFormLayout(self)
        form.setSpacing(8)
        self.pin = QLineEdit()
        self.pin.setPlaceholderText(tr("PIN from Moonlight, e.g. 1234"))
        self.pin.setMaxLength(4)
        self.name = QLineEdit(default_name)
        form.addRow("PIN", self.pin)
        form.addRow(tr("Device name"), self.name)
        hint = QLabel(tr("Select '{server}' in Moonlight and enter the 4-digit "
                         "PIN it shows here.", server=advertised or default_name))
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(False)
        self.pin.textChanged.connect(
            lambda t: ok.setEnabled(len(t.strip()) == 4 and t.strip().isdigit()))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class WebUiDialog(QDialog):
    """The Sunshine web-UI URL and its generated login, with a button to open
    it. The login is per install, so it is shown here rather than hidden."""

    def __init__(self, parent, url: str, user: str, password: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Sunshine web UI"))
        self.setMinimumWidth(400)
        form = QFormLayout(self)
        form.setSpacing(8)
        for label, value in (("URL", url), (tr("User"), user),
                             (tr("Password"), password)):
            field = QLineEdit(value)
            field.setReadOnly(True)
            field.setCursorPosition(0)
            form.addRow(label, field)
        buttons = QDialogButtonBox()
        copy_btn = buttons.addButton(tr("Copy password"),
                                     QDialogButtonBox.ButtonRole.ActionRole)
        open_btn = buttons.addButton(tr("Open in browser"),
                                     QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(tr("Close"), QDialogButtonBox.ButtonRole.RejectRole)
        copy_btn.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(password))
        # Must not close the dialog: on Wayland openUrl goes through the
        # desktop portal and the request dies with the parent window.
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class SessionPage(QWidget):
    def __init__(self, ctx) -> None:
        super().__init__()
        self._ctx = ctx
        self._pool: list = []
        self._pending: str | None = None  # "start" | "stop" while a worker runs
        self._last_error = ""
        # GPU vendor decides which encoder-tuning panel and telemetry rows the
        # page shows (NVENC vs VAAPI). Resolved once; PS_GPU_VENDOR overrides.
        self._nvidia = runtime.gpu_vendor() not in runtime.MESA_VENDORS
        self._build()
        ctx.config_changed.connect(self._reload_profiles)
        self._reload_profiles()

    # -- layout ----------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        root.addWidget(self._build_session_card())
        root.addWidget(self._build_preview_card())
        root.addWidget(self._build_load_card())
        root.addWidget(self._build_quality_card())
        root.addStretch(1)

    def _build_session_card(self) -> QWidget:
        frame, lay = card(tr("Session"))
        top = QHBoxLayout()
        top.setSpacing(8)
        self._client = QComboBox()
        self._client.currentTextChanged.connect(self._on_profile_selected)
        self._start_btn = QPushButton(tr("Start"))
        self._start_btn.setProperty("primary", True)
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn = QPushButton(tr("Stop"))
        self._stop_btn.setProperty("danger", True)
        self._stop_btn.clicked.connect(self._on_stop)
        self._pair_btn = QPushButton(tr("Pair …"))
        self._pair_btn.setToolTip(tr("Pair a new Moonlight client by PIN "
                                     "(session must be running)"))
        self._pair_btn.setEnabled(False)
        self._pair_btn.clicked.connect(self._on_pair)
        # "Sandbox", not "Client": the box picks the profile whose
        # sandbox is streamed. The clients are the Moonlight devices
        # paired to it, which is what the Pair button next to it means.
        top.addWidget(QLabel(tr("Sandbox")))
        top.addWidget(self._client, 1)
        top.addWidget(self._start_btn)
        top.addWidget(self._stop_btn)
        top.addWidget(self._pair_btn)
        lay.addLayout(top)

        self._state = QLabel("…")
        self._state.setObjectName("sessionState")
        lay.addWidget(self._state)
        self._detail = QLabel("")
        self._detail.setProperty("muted", True)
        self._detail.setWordWrap(True)
        lay.addWidget(self._detail)

        self._game = InfoRow(tr("Game"))
        self._resolution = InfoRow(tr("Resolution"))
        # The backend is a per-profile setting, not just a status line, and it
        # belongs here as well as in the profile dialog: comparing the two is
        # exactly what this page is for. Editable while stopped; while a
        # session runs it shows the running backend and locks, since a switch
        # could not take effect anyway.
        self._backend_row = QWidget()
        brow = QHBoxLayout(self._backend_row)
        brow.setContentsMargins(0, 0, 0, 0)
        brow.setSpacing(8)
        caption = QLabel(tr("Backend"))
        caption.setProperty("muted", True)
        caption.setFixedWidth(
            max(48, caption.fontMetrics().horizontalAdvance(tr("Backend")) + 4))
        self._backend_row.caption_label = caption
        self._backend = QComboBox()
        for spec in backends.BACKENDS.values():
            self._backend.addItem(spec.label, spec.name)
        self._backend.currentIndexChanged.connect(self._on_backend_selected)
        brow.addWidget(caption)
        brow.addWidget(self._backend)
        brow.addStretch(1)
        align_captions(self._game, self._resolution, self._backend_row)
        for w in (self._game, self._resolution, self._backend_row):
            lay.addWidget(w)
        return frame

    def _build_preview_card(self) -> QWidget:
        frame, lay = card(tr("Preview"))
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(QLabel(tr("Refresh every")))
        self._preview_interval = QSpinBox()
        # Click-only focus: otherwise disabling Start on session start hands
        # keyboard focus to this box, which selects its value (blue highlight).
        self._preview_interval.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._preview_interval.setRange(0, 300)
        self._preview_interval.setSpecialValueText(tr("off"))  # 0 → off
        self._preview_interval.setToolTip(tr(
            "How often the in-container preview is captured; 0 turns it off. "
            "Applies from the next stream start."))
        # valueChanged only toggles the unit label (cheap, no save); persistence
        # is on editingFinished so typing isn't interrupted by a save→reload.
        self._preview_interval.valueChanged.connect(
            lambda v: self._sec_label.setVisible(v > 0))
        self._preview_interval.editingFinished.connect(self._persist_preview)
        header.addWidget(self._preview_interval)
        # "s" as a separate unit label, not baked into the editable field; hidden
        # when the value is 0 ("off").
        self._sec_label = QLabel("s")
        self._sec_label.setProperty("muted", True)
        header.addWidget(self._sec_label)
        header.addStretch(1)
        lay.addLayout(header)

        self._thumb = AspectPixmapLabel()
        self._thumb.setText(tr("Preview appears here while streaming."))
        self._thumb.setProperty("muted", True)
        self._thumb_pix: QPixmap | None = None
        self._thumb_mtime = 0.0  # skip reloading an unchanged preview each poll
        lay.addWidget(self._thumb)
        return frame

    def _build_load_card(self) -> QWidget:
        frame, lay = card(tr("Performance"))
        # Game FPS from the in-container probe (experimental feature, off by
        # default): the row only exists while it is switched on.
        self._fps = InfoRow("FPS")
        lay.addWidget(self._fps)
        self._cpu = Meter("CPU")
        self._ram = Meter("RAM")
        self._gpu = Meter("GPU")
        self._vram = Meter("VRAM")
        rows = [self._cpu, self._ram, self._gpu, self._vram]
        # The NVENC session count is an NVIDIA-only signal (nvidia-smi); the
        # amdgpu kernel interface exposes no per-encoder counter (Intel gets
        # only a busy % via intel_gpu_top), so drop the row rather than show a
        # permanently empty one.
        self._nvenc = InfoRow("NVENC") if self._nvidia else None
        if self._nvenc is not None:
            rows.append(self._nvenc)
        for w in rows:
            lay.addWidget(w)
        return frame

    def _build_quality_card(self) -> QWidget:
        frame, lay = card(tr("Stream quality"))
        # The two backends expose entirely different knobs, so the card swaps
        # its panel with the selected profile's backend rather than greying
        # one set out (see _load_backend).
        self._sunshine_panel = QWidget()
        row = QHBoxLayout(self._sunshine_panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        # NVENC (NVIDIA) and VAAPI (AMD/Intel) expose different encoder knobs;
        # the runtime already picks the matching Sunshine encoder by GPU vendor.
        if self._nvidia:
            self._build_nvenc_row(row)
        else:
            self._build_vaapi_row(row)
        lay.addWidget(self._sunshine_panel)
        self._moonshine_panel = self._build_moonshine_row()
        lay.addWidget(self._moonshine_panel)

        bottom = QHBoxLayout()
        self._quality_hint = QLabel(tr(
            "Bitrate & codec are chosen by the Moonlight client; these control "
            "encoder quality on the server side."))
        self._quality_hint.setProperty("muted", True)
        self._quality_hint.setWordWrap(True)
        self._apply_btn = QPushButton(tr("Apply live"))
        self._apply_btn.setToolTip(tr("Apply immediately to the running session "
                                      "(stream briefly reconnects)"))
        self._apply_btn.clicked.connect(self._on_apply_quality)
        self._web_btn = QPushButton(tr("Open Sunshine web UI"))
        self._web_btn.clicked.connect(self._open_web_ui)
        bottom.addWidget(self._quality_hint, 1)
        bottom.addWidget(self._apply_btn)
        bottom.addWidget(self._web_btn)
        lay.addLayout(bottom)
        return frame

    def _build_moonshine_row(self) -> QWidget:
        """moonshine's one transport knob. It has no config API, so this is
        saved to the profile and applied at the next session start."""
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._fec = QSpinBox()
        self._fec.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # -1 is the minimum so it can carry the special text: 0 is a real
        # setting of its own ("no FEC"), not a stand-in for "leave default".
        self._fec.setRange(-1, 100)
        # Spell the default out, because the value one step below it is 0,
        # which switches error correction OFF entirely. Without the number the
        # safe setting and the most harmful one in the box sit next to each
        # other and read alike.
        self._fec.setSpecialValueText(
            tr("moonshine default ({pct} %)", pct=config.MOONSHINE_FEC_DEFAULT))
        self._fec.setSuffix(" %")
        self._fec.setToolTip(tr(
            "Forward error correction: how much redundancy is sent so lost "
            "packets do not become visible artifacts. Higher survives a lossy "
            "WiFi and costs bandwidth. 0 turns it off, and then every lost "
            "packet is visible in the picture."))
        self._fec.editingFinished.connect(self._persist_moonshine)
        row.addWidget(QLabel(tr("Error correction")))
        row.addWidget(self._fec)
        row.addStretch(1)
        return panel

    def _persist_moonshine(self) -> None:
        sc = self._profile()
        if sc is None:
            return
        sc.moonshine_fec_percent = self._fec.value()
        self._ctx.save()
        self._quality_hint.setText(tr("Saved. Applies at the next session start."))

    def _build_nvenc_row(self, row: QHBoxLayout) -> None:
        self._preset = QComboBox()
        for value in ("1", "2", "3", "4", "5", "6", "7"):
            self._preset.addItem(f"P{value} · {_PRESET_LABELS[value]()}", value)
        self._twopass = QComboBox()
        for value in ("disabled", "quarter_res", "full_res"):
            self._twopass.addItem(_TWOPASS_LABELS[value](), value)
        self._vbv = QSpinBox()
        self._vbv.setRange(0, 400)
        self._vbv.setSingleStep(25)
        self._vbv.setToolTip(tr(
            "VBV buffer increase (%): a larger buffer reduces artifacts in fast "
            "motion at the same bitrate. 0 = Sunshine default."))
        # Combos persist on change (survives restarts). The spinbox persists on
        # editingFinished (Enter / focus-out), NOT valueChanged: saving on every
        # keystroke emits config_changed → reload → setValue, which would clobber
        # the digits you're still typing. The button applies to a LIVE session.
        self._preset.currentIndexChanged.connect(self._persist_quality)
        self._twopass.currentIndexChanged.connect(self._persist_quality)
        self._vbv.editingFinished.connect(self._persist_quality)
        row.addWidget(QLabel(tr("NVENC preset")))
        row.addWidget(self._preset, 1)
        row.addWidget(QLabel("Two-Pass"))
        row.addWidget(self._twopass, 1)
        row.addWidget(QLabel("VBV"))
        row.addWidget(self._vbv)
        vbv_unit = QLabel("%")
        vbv_unit.setProperty("muted", True)
        row.addWidget(vbv_unit)

    def _build_vaapi_row(self, row: QHBoxLayout) -> None:
        self._vaapi_quality = QComboBox()
        for value in ("auto", "speed", "balanced", "quality"):
            self._vaapi_quality.addItem(_VAAPI_QUALITY_LABELS[value](), value)
        self._vaapi_quality.setToolTip(tr(
            "VAAPI quality profile: the encoder's speed/quality tradeoff."))
        self._vaapi_rc = QComboBox()
        for value in ("auto", "vbr", "cbr", "cqp", "icq", "qvbr", "avbr"):
            self._vaapi_rc.addItem(_VAAPI_RC_LABELS[value](), value)
        self._vaapi_rc.setToolTip(tr(
            "VAAPI rate-control mode. 'auto' lets the driver choose; not every "
            "mode is supported on every GPU."))
        self._vaapi_strict = QCheckBox(tr("Strict RC buffer"))
        self._vaapi_strict.setToolTip(tr(
            "Avoids dropped frames over the network during scene changes, but "
            "quality may drop during motion."))
        self._vaapi_quality.currentIndexChanged.connect(self._persist_quality)
        self._vaapi_rc.currentIndexChanged.connect(self._persist_quality)
        self._vaapi_strict.toggled.connect(self._persist_quality)
        row.addWidget(QLabel(tr("VAAPI quality")))
        row.addWidget(self._vaapi_quality, 1)
        row.addWidget(QLabel(tr("Rate control")))
        row.addWidget(self._vaapi_rc, 1)
        row.addWidget(self._vaapi_strict)

    # -- profiles --------------------------------------------------------
    def _profile(self) -> config.SessionConfig | None:
        return self._ctx.config.get(self._client.currentText())

    def _reload_profiles(self) -> None:
        current = self._client.currentText()
        self._client.blockSignals(True)
        self._client.clear()
        self._client.addItems([s.name for s in self._ctx.config.sessions])
        if current:
            idx = self._client.findText(current)
            self._client.setCurrentIndex(max(idx, 0))
        self._client.blockSignals(False)
        self._on_profile_selected()

    def _on_profile_selected(self, _name: str = "") -> None:
        sc = self._profile()
        if sc is None:
            return
        self._load_quality(sc)
        self._load_backend(sc)
        self._load_preview(sc)

    def _set_backend_combo(self, name: str) -> None:
        idx = self._backend.findData(name)
        if idx < 0 or idx == self._backend.currentIndex():
            return
        self._backend.blockSignals(True)
        self._backend.setCurrentIndex(idx)
        self._backend.blockSignals(False)

    def _on_backend_selected(self) -> None:
        """Write the picked backend to the profile.

        It cannot apply to a running session (different server, different
        pairings), so the box is disabled while one runs and this only ever
        fires from the stopped state.
        """
        sc = self._profile()
        chosen = self._backend.currentData()
        if sc is None or not chosen or chosen == sc.backend:
            return
        sc.backend = chosen
        self._ctx.save()
        self._load_backend(sc)     # swap the quality panel with it
        self._load_preview(sc)

    def _load_backend(self, sc: config.SessionConfig) -> None:
        """Show the panel that belongs to this profile's backend.

        Sunshine has encoder knobs applied through its config API; moonshine
        has one transport knob and no API, so its value is saved to the
        profile and takes effect at the next start. The web UI button is
        Sunshine's alone.
        """
        spec = backends.get_or_default(sc.backend)
        self._set_backend_combo(spec.name)
        sunshine = spec.name == backends.SUNSHINE.name
        self._sunshine_panel.setVisible(sunshine)
        self._moonshine_panel.setVisible(not sunshine)
        self._apply_btn.setVisible(spec.live_config)
        self._web_btn.setVisible(spec.web_port_off is not None)
        if sunshine:
            self._quality_hint.setText(tr(
                "Bitrate & codec are chosen by the Moonlight client; these "
                "control encoder quality on the server side."))
        else:
            self._fec.blockSignals(True)
            self._fec.setValue(sc.moonshine_fec_percent)
            self._fec.blockSignals(False)
            self._quality_hint.setText(tr(
                "Bitrate & codec are chosen by the Moonlight client. "
                "{backend} has no config API, so this applies at the next "
                "session start.", backend=spec.label))

    def _load_preview(self, sc: config.SessionConfig) -> None:
        if self._preview_interval.hasFocus():  # don't clobber an in-progress edit
            return
        self._preview_interval.blockSignals(True)
        self._preview_interval.setValue(sc.preview_interval_s)
        self._preview_interval.blockSignals(False)
        self._sec_label.setVisible(sc.preview_interval_s > 0)

    def _persist_preview(self) -> None:
        """Save the preview interval to the profile; takes effect next start."""
        self._sec_label.setVisible(self._preview_interval.value() > 0)
        sc = self._profile()
        if sc is None:
            return
        sc.preview_interval_s = self._preview_interval.value()
        self._ctx.save()

    def _load_quality(self, sc: config.SessionConfig) -> None:
        if self._nvidia:
            self._load_nvenc_quality(sc)
        else:
            self._load_vaapi_quality(sc)

    def _load_nvenc_quality(self, sc: config.SessionConfig) -> None:
        preset = sc.sunshine_extra.get("nvenc_preset", "1")
        twopass = sc.sunshine_extra.get("nvenc_twopass", "quarter_res")
        # blockSignals: loading must not trip _persist_quality (it would write
        # the config back on every profile switch and could recurse).
        for box, data in ((self._preset, preset), (self._twopass, twopass)):
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(data)))
            box.blockSignals(False)
        if not self._vbv.hasFocus():  # never overwrite an in-progress edit
            self._vbv.blockSignals(True)
            try:
                self._vbv.setValue(int(sc.sunshine_extra.get("nvenc_vbv_increase", "0")))
            except ValueError:
                self._vbv.setValue(0)
            self._vbv.blockSignals(False)

    def _load_vaapi_quality(self, sc: config.SessionConfig) -> None:
        quality = sc.sunshine_extra.get("vaapi_quality", "auto")
        rc = sc.sunshine_extra.get("vaapi_rc", "auto")
        strict = sc.sunshine_extra.get("vaapi_strict_rc_buffer", "disabled")
        for box, data in ((self._vaapi_quality, quality), (self._vaapi_rc, rc)):
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(data)))
            box.blockSignals(False)
        self._vaapi_strict.blockSignals(True)
        self._vaapi_strict.setChecked(strict == "enabled")
        self._vaapi_strict.blockSignals(False)

    def _quality_changes(self) -> dict[str, str]:
        if self._nvidia:
            return {"nvenc_preset": self._preset.currentData(),
                    "nvenc_twopass": self._twopass.currentData(),
                    "nvenc_vbv_increase": str(self._vbv.value())}
        return {"vaapi_quality": self._vaapi_quality.currentData(),
                "vaapi_rc": self._vaapi_rc.currentData(),
                "vaapi_strict_rc_buffer":
                    "enabled" if self._vaapi_strict.isChecked() else "disabled"}

    def _persist_quality(self) -> None:
        """Save the current dropdown selection to the profile immediately, so
        it survives restarts even without a live 'apply'."""
        sc = self._profile()
        if sc is None:
            return
        sc.sunshine_extra.update(self._quality_changes())
        self._ctx.save()
        self._quality_hint.setText(tr(
            "Saved. Applies from the next stream start; use 'Apply live' for a "
            "running session."))

    # -- snapshot rendering ---------------------------------------------
    def on_snapshot(self, snap: monitor.Snapshot) -> None:
        busy = self._pending is not None
        if busy:
            self._set_state("busy", tr("starting …") if self._pending == "start"
                            else tr("stopping …"))
        elif snap.running:
            owner = f" · {snap.client_profile}" if snap.client_profile else ""
            self._set_state("running", tr("● running") + owner)
            self._detail.setText(self._last_error)
        elif self._last_error:
            self._set_state("error", tr("Error"))
            self._detail.setText(self._last_error)
        else:
            self._set_state("stopped", tr("○ stopped"))
            self._detail.setText("")

        self._start_btn.setEnabled(not busy and not snap.running)
        self._stop_btn.setEnabled(not busy and snap.running)
        self._pair_btn.setEnabled(not busy and snap.running)

        self._game.set(snap.game.name if snap.game else
                       (tr("Big Picture / menu") if snap.running else None))
        self._update_resolution(snap.running)
        # The row means the streaming backend, not the container state: one
        # word with two meanings in the same window is worse than no row.
        # Running: what the container actually runs, box locked, since
        # switching cannot take effect. Stopped: the profile's choice,
        # editable.
        sc = self._profile()
        self._set_backend_combo(snap.backend if snap.running
                                else (sc.backend if sc else backends.DEFAULT))
        self._backend.setEnabled(not snap.running)
        self._backend.setToolTip(
            tr("Stop the session to switch the backend.") if snap.running
            else tr("Applies at the next session start. Each backend keeps its "
                    "own pairings, so a client paired to one must be paired "
                    "again for the other."))
        self._update_perf(snap)
        self._update_load(snap)
        self._update_thumbnail(snap.running)

    def _update_resolution(self, running: bool) -> None:
        """With dynamic resolution the render size is only known once a client
        connects (the container drops it into the mounted HOME). Sunshine locks
        the first client's mode until the session restarts; moonshine rebuilds
        compositor and gamescope per session, so it follows every reconnect."""
        sc = self._profile()
        if not running or sc is None:
            self._resolution.set(None)
            return
        if not sc.dynamic_resolution:
            self._resolution.set(None if sc.is_ask() else sc.resolution)
            return
        try:
            w, h, r = (sc.home_dir() / ".cache/podstage/client-mode") \
                .read_text().split()
        except (OSError, ValueError):
            self._resolution.set(tr("waiting for the first client …"))
            return
        if backends.get_or_default(sc.backend).res_locked:
            self._resolution.set(tr(
                "{w}x{h}@{r} · locked until the session restarts",
                w=w, h=h, r=r))
        else:
            self._resolution.set(tr(
                "{w}x{h}@{r} · follows the connected client", w=w, h=h, r=r))

    def _update_thumbnail(self, running: bool) -> None:
        """Show the preview frame the in-container loop drops into the mounted
        sandbox HOME (<homes root>/<client>/.cache/podstage/thumb.png). The card is
        always visible; the image area shows a frame or a muted placeholder."""
        sc = self._profile()
        if sc is None or not running:
            self._show_thumb_placeholder(tr("Preview appears here while streaming."))
            return
        interval = sc.preview_interval_s
        if interval <= 0:
            self._show_thumb_placeholder(tr("Preview is off"))
            return
        path = sc.home_dir() / ".cache/podstage/thumb.png"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._show_thumb_placeholder(tr("waiting for preview …"))
            return
        if self._ctx.config.preview_keep_last:
            # Neither capture path delivers continuously: wlr-screencopy hands
            # out no frame while the picture is static, and under moonshine
            # gamescope exists only while a client is connected. Keep the last
            # frame, but never one from a previous session.
            stale = mtime < (runtime.load_state() or {}).get("started", 0)
        else:
            # Strict mode (Setup toggle): hide a frame once it is older than a
            # few capture cycles.
            stale = time.time() - mtime >= max(THUMB_MAX_AGE_S, interval * 3)
        if stale:
            self._show_thumb_placeholder(tr("waiting for preview …"))
            return
        if self._thumb_pix is not None and mtime == self._thumb_mtime:
            return  # unchanged since last poll — skip the reload + relayout
        pix = QPixmap()
        if pix.load(str(path)):
            self._thumb_pix = pix
            self._thumb_mtime = mtime
            self._thumb.set_source(pix)
        else:
            self._show_thumb_placeholder(tr("waiting for preview …"))

    def _show_thumb_placeholder(self, text: str) -> None:
        if self._thumb_pix is None and self._thumb.text() == text:
            return  # already showing this placeholder — avoid a per-poll relayout
        self._thumb_pix = None
        self._thumb.set_source(None)
        self._thumb.setText(text)

    def _set_state(self, state: str, text: str) -> None:
        self._state.setText(text)
        if self._state.property("state") != state:  # repolish only on change
            self._state.setProperty("state", state)
            theme.repolish(self._state)

    def _update_perf(self, snap: monitor.Snapshot) -> None:
        """Current FPS from the in-container probe. The row is hidden while
        the setting is off, so nobody stares at a permanent dash."""
        self._fps.setVisible(self._ctx.config.perf_metrics)
        perf = snap.perf if snap.running else None
        if perf is None:
            self._fps.set(None)
        elif perf.fps:
            self._fps.set(f"{perf.fps:.0f} fps")
        else:
            # gamescope reports a frametime only for a genuinely new present, so
            # a static Big Picture page yields nothing. That is a state, not a
            # missing reading, and a bare dash reads like a broken probe.
            self._fps.set(tr("no new frames"))

    def _update_load(self, snap: monitor.Snapshot) -> None:
        # Whole machine, both backends: the session's own cgroup was located
        # through labwc, which moonshine does not run (monitor.host_stats).
        h = snap.host
        if h and h.cpu_pct is not None:
            self._cpu.set(h.cpu_pct, f"{h.cpu_pct:.0f} %")
        else:
            self._cpu.set(None)
        total_mb = (h.mem_total_mb if h and h.mem_total_mb else _RAM_TOTAL_MB)
        if h and h.mem_used_mb and total_mb:
            self._ram.set(h.mem_used_mb * 100 / total_mb,
                          f"{h.mem_used_mb} / {total_mb} MB")
        else:
            self._ram.set(None)

        g = snap.gpu
        self._gpu.set(g.util_pct if g else None,
                      f"{g.util_pct} %" if g and g.util_pct is not None else "")
        if g and g.mem_used_mb and g.mem_total_mb:
            self._vram.set(g.mem_used_mb * 100 / g.mem_total_mb,
                           f"{g.mem_used_mb} / {g.mem_total_mb} MB")
        else:
            self._vram.set(None)
        if self._nvenc is not None:
            self._nvenc.set(tr("{n} session(s)", n=g.encoder_sessions)
                            if g and g.encoder_sessions is not None else None)

    # -- start / stop ----------------------------------------------------
    def _on_start(self) -> None:
        sc = self._profile()
        if sc is None:
            return
        session = Session(sc, app_config=self._ctx.config)
        if not sandbox.is_bootstrapped(session.home):
            self._last_error = tr("'{name}' is not set up. Start the Steam "
                                  "login on the 'Sandboxes' page.", name=sc.name)
            return
        if not sandbox.steam_logged_in(session.home):
            self._last_error = tr("'{name}' has no Steam login yet. Log in via "
                                  "the 'Sandboxes' page first.", name=sc.name)
            return
        close_sandbox_steam = False
        if session.sandbox_steam_running():
            answer = QMessageBox.question(
                self, tr("Close sandbox Steam?"),
                tr("The sandbox Steam is open on the desktop. Close it and "
                   "start the stream?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if answer != QMessageBox.StandardButton.Yes:
                return
            close_sandbox_steam = True
        resolution = None
        if sc.is_ask():
            resolution = self._ask_resolution(sc.name)
            if resolution is None:
                return

        def _launch() -> runtime.RuntimeStatus:
            if close_sandbox_steam and not session.close_sandbox_steam():
                raise RuntimeError(tr(
                    "Could not close the sandbox Steam; close it manually."))
            return session.start(resolution=resolution)

        self._last_error = ""
        self._pending = "start"
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._set_state("busy", tr("starting …"))
        self._detail.setText(tr("Starting container (provisioning + podman) …"))
        start_action(self._pool, _launch, f"Start {sc.name}", self._on_action_done)

    def _on_stop(self) -> None:
        sc = self._profile()
        if sc is None:
            return
        self._last_error = ""
        self._pending = "stop"
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._set_state("busy", tr("stopping …"))
        self._detail.setText("")
        start_action(self._pool, lambda: Session(sc).stop(),
                     f"Stop {sc.name}", self._on_action_done)

    def _ask_resolution(self, name: str) -> str | None:
        presets = ["{}x{}@{}".format(*dims)
                   for dims in config.RESOLUTION_PRESETS.values()]
        value, ok = QInputDialog.getItem(
            self, tr("Resolution"),
            tr("'{name}' picks its resolution at startup.\nResolution for this "
               "session:", name=name),
            presets, 0, True)
        return value.strip() if ok and value.strip() else None

    def _on_action_done(self, ok: bool, msg: str) -> None:
        self._pending = None
        if not ok:
            self._last_error = msg
        # the next snapshot re-renders buttons + state

    # -- pairing ---------------------------------------------------------
    def _on_pair(self) -> None:
        sc = self._profile()
        if sc is None:
            return
        spec = backends.get_or_default(sc.backend)
        dlg = PairDialog(self, sc.name, spec.advertised_name(sc.name))
        # moonshine records no client names, so asking for one would suggest
        # a label that is never stored anywhere.
        dlg.name.setEnabled(spec.name == backends.SUNSHINE.name)
        if not dlg.exec():
            return
        pin = dlg.pin.text().strip()
        name = dlg.name.text().strip() or sc.name
        base = sc.sunshine_port_base
        home = sc.home_dir()
        self._pair_btn.setEnabled(False)
        failed = tr("The PIN was submitted but no pairing completed. Restart "
                    "the pairing in Moonlight and enter the new PIN.")

        def _pair() -> str:
            if spec.name == backends.MOONSHINE.name:
                if not moonshine_api.pair_verified(pin, home, port=base):
                    raise RuntimeError(failed)
                return tr("Paired. Moonlight can stream now.")
            if not sunshine_api.pair_verified(pin, name, home, base + 1):
                raise RuntimeError(failed)
            return tr("Client '{name}' paired. Moonlight can stream now.", name=name)

        start_action(self._pool, _pair, "Pairing", self._on_pair_done)

    def _on_pair_done(self, ok: bool, msg: str) -> None:
        self._last_error = msg if ok else tr("Pairing failed: {msg}", msg=msg)
        self._pair_btn.setEnabled(True)

    # -- quality ---------------------------------------------------------
    def _on_apply_quality(self) -> None:
        sc = self._profile()
        if sc is None:
            return
        if not backends.get_or_default(sc.backend).live_config:
            self._quality_hint.setText(tr(
                "The {backend} backend has no live quality settings; these "
                "apply to Sunshine profiles only.",
                backend=backends.get_or_default(sc.backend).label))
            return
        changes = self._quality_changes()
        sc.sunshine_extra.update(changes)  # already persisted on change; idempotent
        self._ctx.save()
        st = runtime.status()
        if st.running and st.client in (None, "", sc.name):
            web_port = sc.sunshine_port_base + 1
            self._quality_hint.setText(tr("Applying live … (stream briefly interrupts)"))

            def _apply() -> str:
                sunshine_api.set_options(changes, web_port)
                sunshine_api.restart(web_port)
                return tr("Applied live. The stream is reconnecting.")

            start_action(self._pool, _apply, "Quality", self._on_quality_done)
        else:
            self._quality_hint.setText(tr("No running session. The setting is "
                                          "saved and applies from the next start."))

    def _on_quality_done(self, ok: bool, msg: str) -> None:
        self._quality_hint.setText(msg if ok else
                                   tr("Saved; live apply failed: {msg}", msg=msg))

    def _open_web_ui(self) -> None:
        sc = self._profile()
        port = (sc.sunshine_port_base if sc else 47989) + 1
        user, password = config.sunshine_web_credentials()
        WebUiDialog(self, f"https://localhost:{port}", user, password).exec()
