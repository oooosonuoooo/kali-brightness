#!/usr/bin/env python3
# ============================================================
# KALI GLASS CONTROLLER v2.0
# A display control center for Kali Linux (X11)
# License: MIT
# ============================================================

import sys
import os
import subprocess
import json
import shutil
import time
import math
import datetime
import logging
import shlex

from PyQt5.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QFrame, QAction, QCheckBox, QTimeEdit,
    QComboBox, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, QTime, pyqtSignal, QProcess
from PyQt5.QtGui import (
    QIcon, QPainter, QPixmap, QColor, QCursor,
    QLinearGradient
)
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

# ============================================================
# CONSTANTS
# ============================================================
APP_NAME        = "Kali Glass"
APP_VERSION     = "2.0"
LOCK_NAME       = "kali-glass-single-instance-lock"
CONFIG_FILE     = os.path.expanduser(
    os.environ.get("KALI_GLASS_CONFIG", "~/.config/kali_glass/config.json")
)
CONFIG_DIR      = os.path.dirname(CONFIG_FILE)
LOG_FILE        = os.path.expanduser(
    os.environ.get("KALI_GLASS_LOG", "~/.config/kali_glass/kali_glass.log")
)

# Slider limits
BRIGHT_MIN, BRIGHT_MAX, BRIGHT_DEF   = 1, 100, 100
CONTRAST_MIN, CONTRAST_MAX, CONTRAST_DEF = 10, 100, 50
GAMMA_MIN, GAMMA_MAX, GAMMA_DEF      = 50, 200, 100
TEMP_MIN, TEMP_MAX, TEMP_DEF         = 1000, 6500, 6500
RGB_MIN, RGB_MAX, RGB_DEF            = 10, 100, 100
VIB_MIN, VIB_MAX, VIB_DEF            = 0, 100, 0
HUE_MIN, HUE_MAX, HUE_DEF            = 0, 360, 0

DEBOUNCE_MS    = 150    # slider debounce delay
SCHEDULE_MS    = 30000  # schedule check interval
CMD_TIMEOUT    = 5      # subprocess timeout seconds
STARTUP_APPLY_DELAYS_MS = (300, 2500, 7000, 15000)
NIGHT_TEMP     = 3200
DAY_TEMP       = 6500

# ============================================================
# LOGGING SETUP
# ============================================================
os.makedirs(CONFIG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("kali_glass")

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def clamp(val, lo, hi):
    try:
        numeric = float(val)
    except (TypeError, ValueError):
        numeric = float(lo)

    bounded = max(lo, min(hi, numeric))
    if isinstance(lo, int) and isinstance(hi, int):
        return int(round(bounded))
    return bounded

def get_display_env():
    return os.environ.get("DISPLAY", "")

def has_display_session():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

def _normalize_cmd(cmd):
    if isinstance(cmd, (list, tuple)):
        return [str(part) for part in cmd]
    return shlex.split(str(cmd))

def run_cmd(cmd, timeout=CMD_TIMEOUT, silent=False):
    env = os.environ.copy()
    args = _normalize_cmd(cmd)
    display_cmd = shlex.join(args)
    try:
        result = subprocess.run(
            args, shell=False, capture_output=True, text=True,
            timeout=timeout, env=env, check=False
        )
        ok = result.returncode == 0
        if not ok and not silent:
            log.debug("cmd non-zero [%d]: %s | %s",
                      result.returncode, display_cmd[:120], result.stderr.strip())
        return ok, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        log.warning("Command timed out (%ds): %s", timeout, display_cmd[:120])
        return False, "", "timeout"
    except Exception as e:
        if not silent:
            log.error("Command error: %s | %s", display_cmd[:120], e)
        return False, "", str(e)

def detect_displays():
    xrandr_path = shutil.which("xrandr")
    if not xrandr_path:
        log.warning("xrandr not found")
        return []
    if not get_display_env():
        log.debug("DISPLAY not set; skipping xrandr display detection")
        return []
    ok, out, _ = run_cmd([xrandr_path, "--query"], silent=True)
    if not ok or not out.strip():
        return []
    monitors = []
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "connected":
            monitors.append(parts[0])
    return monitors

def config_time(hour, minute, default_hour, default_minute):
    try:
        hour = int(hour)
        minute = int(minute)
    except (TypeError, ValueError):
        return QTime(default_hour, default_minute)
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return QTime(hour, minute)
    return QTime(default_hour, default_minute)

def is_wayland():
    return bool(
        os.environ.get("WAYLAND_DISPLAY") or
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )

# ============================================================
# CUSTOM WIDGETS
# ============================================================

class NeonSlider(QWidget):
    changed = pyqtSignal()

    def __init__(self, name, min_val, max_val, init_val,
                 color_hex, suffix="", tooltip=""):
        super().__init__()
        self._suffix = suffix
        self._color  = color_hex

        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(0, 4, 0, 4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        self.lbl_name = QLabel(name.upper())
        self.lbl_name.setStyleSheet(
            f"color: {color_hex}; font-size: 9px; font-weight: bold; "
            f"letter-spacing: 1.5px; background: transparent;"
        )

        self.lbl_val = QLabel(f"{init_val}{suffix}")
        self.lbl_val.setStyleSheet(
            "color: #e0e0e0; font-weight: bold; font-size: 10px; "
            "background: transparent;"
        )
        self.lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_val.setMinimumWidth(45)

        row.addWidget(self.lbl_name)
        row.addStretch()
        row.addWidget(self.lbl_val)
        layout.addLayout(row)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(int(init_val))
        self.slider.setCursor(Qt.PointingHandCursor)
        if tooltip:
            self.slider.setToolTip(tooltip)
            self.lbl_name.setToolTip(tooltip)

        self.slider.setStyleSheet(f"""
            QSlider {{ height: 20px; }}
            QSlider::groove:horizontal {{
                height: 5px;
                background: rgba(80,80,80,180);
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: qradialgradient(cx:0.5,cy:0.5,radius:0.5,
                    fx:0.5,fy:0.5,
                    stop:0 white, stop:0.5 {color_hex}, stop:1 {color_hex});
                width: 16px; height: 16px;
                margin: -6px 0;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,60);
            }}
            QSlider::handle:horizontal:hover {{
                background: white;
                border: 2px solid {color_hex};
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0,0,0,0), stop:1 {color_hex});
                border-radius: 2px; height: 5px;
            }}
        """)

        self.slider.valueChanged.connect(self._on_change)
        layout.addWidget(self.slider)

    def _on_change(self, val):
        self.lbl_val.setText(f"{val}{self._suffix}")
        self.changed.emit()

    def value(self):
        return self.slider.value()

    def set_value(self, val):
        self.slider.blockSignals(True)
        self.slider.setValue(int(val))
        self.lbl_val.setText(f"{int(val)}{self._suffix}")
        self.slider.blockSignals(False)


class SectionHeader(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setStyleSheet("""
            color: #445;
            font-size: 8px;
            font-weight: bold;
            letter-spacing: 2px;
            padding: 5px 0 2px 0;
            background: transparent;
        """)


class StatusBar(QLabel):
    def __init__(self):
        super().__init__("Ready")
        self.setAlignment(Qt.AlignCenter)
        self._base_style = (
            "font-size: 9px; padding: 4px; background: transparent; "
            "border-top: 1px solid #1a1f2e;"
        )
        self.setStyleSheet(self._base_style + " color: #555;")

    def set_ok(self, msg):
        self.setText(f"✓  {msg}")
        self.setStyleSheet(self._base_style + " color: #00e5ff;")

    def set_warn(self, msg):
        self.setText(f"⚠  {msg}")
        self.setStyleSheet(self._base_style + " color: #ffaa00;")

    def set_err(self, msg):
        self.setText(f"✗  {msg}")
        self.setStyleSheet(self._base_style + " color: #ff4444;")


# ============================================================
# MAIN POPUP WINDOW
# ============================================================

FRAME_STYLE = """
    QFrame#MainFrame {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 rgba(14,17,26,250),
            stop:1 rgba(8,10,16,252));
        border: 1px solid rgba(0,229,255,55);
        border-radius: 14px;
    }
    QLabel {
        font-family: 'Segoe UI', 'DejaVu Sans', sans-serif;
        color: #ccc;
        background: transparent;
    }
    QCheckBox {
        color: #aaa; font-size: 10px;
        spacing: 6px; background: transparent;
    }
    QCheckBox::indicator {
        width: 14px; height: 14px;
        border-radius: 3px;
        border: 1px solid #444; background: #111;
    }
    QCheckBox::indicator:checked {
        background: #00e5ff; border: 1px solid #00e5ff;
    }
    QComboBox {
        background: rgba(30,35,50,200);
        color: #00e5ff;
        border: 1px solid rgba(0,229,255,70);
        padding: 5px 8px; font-size: 10px;
        border-radius: 5px; min-height: 24px;
    }
    QComboBox::drop-down { border: none; width: 20px; }
    QComboBox QAbstractItemView {
        background: #1a1f2e; color: #00e5ff;
        border: 1px solid #333;
        selection-background-color: #00e5ff;
        selection-color: #000;
    }
    QTimeEdit {
        background: rgba(30,35,50,200);
        color: #ffaa00;
        border: 1px solid rgba(255,170,0,70);
        border-radius: 5px; padding: 3px 6px;
        font-weight: bold; font-size: 11px; min-height: 24px;
    }
    QTimeEdit::up-button, QTimeEdit::down-button { width: 0px; }
    QPushButton#ResetBtn {
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 #cc8800, stop:1 #ffcc44);
        color: #111; font-weight: bold;
        border-radius: 5px; padding: 5px 12px;
        font-size: 10px; border: none;
    }
    QPushButton#ResetBtn:hover  { background: #ffdd66; }
    QPushButton#ResetBtn:pressed { background: #aa6600; }
    QPushButton#NightBtn {
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 #440088, stop:1 #8800cc);
        color: #ddd; font-weight: bold;
        border-radius: 5px; padding: 5px 12px;
        font-size: 10px; border: none;
    }
    QPushButton#NightBtn:hover  { background: #aa44ff; color: white; }
    QPushButton#CloseBtn {
        background: transparent; color: #555;
        font-size: 18px; border: none;
        font-weight: bold; padding: 0;
        min-width: 24px; max-width: 24px;
    }
    QPushButton#CloseBtn:hover { color: #ff4444; }
    QPushButton#RefreshBtn {
        background: transparent; color: #444;
        font-size: 13px; border: none;
        padding: 0; min-width: 24px; max-width: 24px;
    }
    QPushButton#RefreshBtn:hover { color: #00e5ff; }
"""


class NeonPopup(QWidget):
    def __init__(self, engine):
        super().__init__()
        self._engine   = engine
        self._drag_pos = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(APP_NAME)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        self.frame = QFrame()
        self.frame.setObjectName("MainFrame")
        self.frame.setStyleSheet(FRAME_STYLE)

        try:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(32)
            shadow.setColor(QColor(0, 229, 255, 55))
            shadow.setOffset(0, 4)
            self.frame.setGraphicsEffect(shadow)
        except Exception:
            pass

        outer.addWidget(self.frame)

        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(18, 14, 18, 14)
        inner.setSpacing(5)
        self._build_ui(inner)
        self.resize(340, 730)

    def _build_ui(self, L):
        # Header
        hdr = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet("color:#00e5ff;font-size:8px;background:transparent;")
        ttl = QLabel(f"  {APP_NAME.upper()}")
        ttl.setStyleSheet(
            "color:#00e5ff;font-weight:bold;letter-spacing:3px;"
            "font-size:11px;background:transparent;"
        )
        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet("color:#333;font-size:8px;background:transparent;")
        cb = QPushButton("×")
        cb.setObjectName("CloseBtn")
        cb.setToolTip("Hide to tray (app keeps running)")
        cb.clicked.connect(self.hide)
        hdr.addWidget(dot)
        hdr.addWidget(ttl)
        hdr.addStretch()
        hdr.addWidget(ver)
        hdr.addSpacing(6)
        hdr.addWidget(cb)
        L.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:rgba(0,229,255,35);border:none;max-height:1px;")
        L.addWidget(sep)
        L.addSpacing(2)

        # Display selector
        L.addWidget(SectionHeader("▸  DISPLAY TARGET"))
        dr = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setToolTip("Select which monitor to control")
        self._populate_displays()
        # FIX: combo change now triggers update
        self.combo.currentIndexChanged.connect(
            lambda: self._engine.schedule_update()
        )
        rb = QPushButton("↺")
        rb.setObjectName("RefreshBtn")
        rb.setToolTip("Refresh display list")
        rb.clicked.connect(self._populate_displays)
        dr.addWidget(self.combo)
        dr.addWidget(rb)
        L.addLayout(dr)

        if is_wayland():
            w = QLabel("⚠  Wayland detected — redshift/xrandr may not work. Use X11.")
            w.setStyleSheet(
                "color:#ffaa00;font-size:9px;background:rgba(255,170,0,15);"
                "padding:4px;border-radius:4px;border:1px solid rgba(255,170,0,35);"
            )
            w.setWordWrap(True)
            L.addWidget(w)

        L.addSpacing(2)
        L.addWidget(SectionHeader("▸  BRIGHTNESS & DISPLAY"))

        self.sl_bright = NeonSlider(
            "Brightness", BRIGHT_MIN, BRIGHT_MAX, BRIGHT_DEF, "#e8e8e8", "%",
            "Screen brightness (1–100%)"
        )
        self.sl_bright.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_bright)

        self.sl_contrast = NeonSlider(
            "Contrast", CONTRAST_MIN, CONTRAST_MAX, CONTRAST_DEF, "#00d4f5", "",
            "Gamma contrast (50 = neutral, >50 = more contrast)"
        )
        self.sl_contrast.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_contrast)

        self.sl_gamma = NeonSlider(
            "Gamma", GAMMA_MIN, GAMMA_MAX, GAMMA_DEF, "#7799ff", "",
            "Gamma multiplier (100 = neutral)"
        )
        self.sl_gamma.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_gamma)

        L.addSpacing(2)
        L.addWidget(SectionHeader("▸  NIGHT MODE"))

        self.sl_temp = NeonSlider(
            "Color Temperature", TEMP_MIN, TEMP_MAX, TEMP_DEF, "#ffaa00", "K",
            "Color warmth: 6500K = daylight | 1000K = warm orange"
        )
        self.sl_temp.slider.setInvertedAppearance(True)
        self.sl_temp.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_temp)

        sr = QHBoxLayout()
        self.check_auto = QCheckBox("Auto Schedule")
        self.check_auto.setToolTip("Auto-switch night mode by time")
        self.check_auto.toggled.connect(self._toggle_sched)
        self.check_auto.toggled.connect(lambda: self._engine.schedule_update())
        sr.addWidget(self.check_auto)
        sr.addStretch()
        L.addLayout(sr)

        self.sched_frame = QWidget()
        self.sched_frame.setStyleSheet("background:transparent;")
        sl = QHBoxLayout(self.sched_frame)
        sl.setContentsMargins(0, 2, 0, 2)
        sl.setSpacing(6)
        on_lbl = QLabel("ON:")
        on_lbl.setStyleSheet("color:#ff5566;font-size:10px;background:transparent;")
        sl.addWidget(on_lbl)
        self.time_on = QTimeEdit()
        self.time_on.setDisplayFormat("HH:mm")
        self.time_on.setTime(QTime(19, 0))
        self.time_on.setToolTip("Night mode start time")
        self.time_on.timeChanged.connect(lambda: self._engine.schedule_update())
        sl.addWidget(self.time_on)
        sl.addSpacing(8)
        off_lbl = QLabel("OFF:")
        off_lbl.setStyleSheet("color:#44aaff;font-size:10px;background:transparent;")
        sl.addWidget(off_lbl)
        self.time_off = QTimeEdit()
        self.time_off.setDisplayFormat("HH:mm")
        self.time_off.setTime(QTime(6, 0))
        self.time_off.setToolTip("Night mode end time")
        self.time_off.timeChanged.connect(lambda: self._engine.schedule_update())
        sl.addWidget(self.time_off)
        sl.addStretch()
        L.addWidget(self.sched_frame)
        self.sched_frame.setVisible(False)

        self.night_status = QLabel("")
        self.night_status.setStyleSheet("color:#ffaa44;font-size:9px;background:transparent;")
        L.addWidget(self.night_status)

        L.addSpacing(2)
        L.addWidget(SectionHeader("▸  RGB CHANNELS"))

        self.sl_r = NeonSlider("Red",   RGB_MIN, RGB_MAX, RGB_DEF, "#ff4455", "%", "Red gamma channel")
        self.sl_r.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_r)

        self.sl_g = NeonSlider("Green", RGB_MIN, RGB_MAX, RGB_DEF, "#44ff88", "%", "Green gamma channel")
        self.sl_g.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_g)

        self.sl_b = NeonSlider("Blue",  RGB_MIN, RGB_MAX, RGB_DEF, "#4488ff", "%", "Blue gamma channel")
        self.sl_b.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_b)

        L.addSpacing(2)
        L.addWidget(SectionHeader("▸  ENHANCEMENTS"))

        self.sl_vib = NeonSlider(
            "Saturation Boost", VIB_MIN, VIB_MAX, VIB_DEF, "#ff00cc", "%",
            "Boost color saturation (0 = none)"
        )
        self.sl_vib.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_vib)

        self.sl_hue = NeonSlider(
            "Hue Shift", HUE_MIN, HUE_MAX, HUE_DEF, "#aa44ff", "°",
            "Rotate color hue (0 = no shift)"
        )
        self.sl_hue.changed.connect(lambda: self._engine.schedule_update())
        L.addWidget(self.sl_hue)

        L.addSpacing(6)
        br = QHBoxLayout()
        br.setSpacing(8)
        self.btn_reset = QPushButton("☀  Day Mode")
        self.btn_reset.setObjectName("ResetBtn")
        self.btn_reset.setToolTip("Reset everything to daytime defaults")
        self.btn_reset.clicked.connect(self._set_day_mode)
        br.addWidget(self.btn_reset)

        self.btn_night = QPushButton("🌙  Night Mode")
        self.btn_night.setObjectName("NightBtn")
        self.btn_night.setToolTip(f"Apply night preset ({NIGHT_TEMP}K warm)")
        self.btn_night.clicked.connect(self._set_night_mode)
        br.addWidget(self.btn_night)
        L.addLayout(br)

        L.addSpacing(4)
        self.status = StatusBar()
        L.addWidget(self.status)

    def _populate_displays(self):
        self.combo.blockSignals(True)
        current = self.combo.currentText()
        self.combo.clear()

        self.combo.addItem("All Displays (Default)")

        monitors = detect_displays()
        if monitors:
            for m in monitors:
                self.combo.addItem(m)
            idx = self.combo.findText(current)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
            else:
                self.combo.setCurrentIndex(0)
        else:
            self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)

    def _toggle_sched(self, checked):
        self.sched_frame.setVisible(checked)

    def _set_day_mode(self):
        self.sl_bright.set_value(BRIGHT_DEF)
        self.sl_contrast.set_value(CONTRAST_DEF)
        self.sl_gamma.set_value(GAMMA_DEF)
        self.sl_temp.set_value(DAY_TEMP)
        self.sl_r.set_value(RGB_DEF)
        self.sl_g.set_value(RGB_DEF)
        self.sl_b.set_value(RGB_DEF)
        self.sl_vib.set_value(VIB_DEF)
        self.sl_hue.set_value(HUE_DEF)
        self.check_auto.setChecked(False)
        self.night_status.setText("")
        self._engine.apply_settings()

    def _set_night_mode(self):
        self.sl_temp.set_value(NIGHT_TEMP)
        self.sl_bright.set_value(70)
        self._engine.apply_settings()

    def current_display(self):
        txt = self.combo.currentText()
        return None if (txt == "Default" or txt == "All Displays (Default)" or not txt) else txt

    def set_night_status(self, is_night):
        if is_night:
            self.night_status.setText("🌙 Night mode active (scheduled)")
        else:
            self.night_status.setText("☀ Day mode active (scheduled)")

    def clear_night_status(self):
        self.night_status.setText("")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def show_near_mouse(self):
        cursor = QCursor.pos()
        # FIX: Find the actual screen where the cursor resides to support multi-monitor setups correctly
        active_screen = QApplication.screenAt(cursor)
        if not active_screen:
            active_screen = QApplication.primaryScreen()
        screen = active_screen.availableGeometry()

        w, h = self.width(), self.height()
        x = min(cursor.x() - w // 2, screen.right() - w - 10)
        y = max(screen.top() + 10, cursor.y() - h - 20)
        x = max(screen.left() + 10, x)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()


# ============================================================
# DISPLAY ENGINE
# ============================================================

class DisplayEngine(QWidget):
    def __init__(self):
        super().__init__()

        # Cache binary paths
        self.redshift_path = shutil.which("redshift")
        self.xrandr_path = shutil.which("xrandr")

        # Initialize native QProcess to manage execution asynchronously (non-blocking)
        self.process = QProcess(self)
        self.process.finished.connect(self._on_process_finished)
        self.process.errorOccurred.connect(self._on_process_error)

        # Track schedule state transitions to prevent overwriting manual settings
        self._last_schedule_state = None
        self._last_applied_info = None
        self._process_queue = []
        self._current_process_label = ""
        self._apply_had_error = False
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._stop_display_process)

        self.ui = NeonPopup(self)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self.apply_settings)

        self._sched_timer = QTimer(self)
        self._sched_timer.timeout.connect(self._check_auto_schedule)
        self._sched_timer.start(SCHEDULE_MS)

        self._check_dependencies()
        self.load_settings()
        self._init_tray()

        # Connect schedule toggle to state transitions
        self.ui.check_auto.toggled.connect(self.on_schedule_toggled)

        for delay_ms in STARTUP_APPLY_DELAYS_MS:
            QTimer.singleShot(delay_ms, self._apply_startup_settings)
        log.info("%s v%s started", APP_NAME, APP_VERSION)

    def _check_dependencies(self):
        missing = []
        if not shutil.which("redshift"):
            missing.append("redshift")
        if not shutil.which("xrandr"):
            missing.append("xrandr (x11-xserver-utils)")
        if missing:
            log.warning("Missing tools: %s", ", ".join(missing))

    def load_settings(self):
        if not os.path.exists(CONFIG_FILE):
            log.info("No config — using defaults")
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            # FIX: use unambiguous key names (old "g" key collision fixed)
            self.ui.sl_bright.set_value(  clamp(d.get("bright",   BRIGHT_DEF),   BRIGHT_MIN,   BRIGHT_MAX))
            self.ui.sl_contrast.set_value(clamp(d.get("contrast", CONTRAST_DEF), CONTRAST_MIN, CONTRAST_MAX))
            self.ui.sl_gamma.set_value(   clamp(d.get("gamma",    GAMMA_DEF),    GAMMA_MIN,    GAMMA_MAX))
            self.ui.sl_temp.set_value(    clamp(d.get("temp",     TEMP_DEF),     TEMP_MIN,     TEMP_MAX))
            self.ui.sl_r.set_value(       clamp(d.get("red",      RGB_DEF),      RGB_MIN,      RGB_MAX))
            self.ui.sl_g.set_value(       clamp(d.get("green",    RGB_DEF),      RGB_MIN,      RGB_MAX))
            self.ui.sl_b.set_value(       clamp(d.get("blue",     RGB_DEF),      RGB_MIN,      RGB_MAX))
            self.ui.sl_vib.set_value(     clamp(d.get("vib",      VIB_DEF),      VIB_MIN,      VIB_MAX))
            self.ui.sl_hue.set_value(     clamp(d.get("hue",      HUE_DEF),      HUE_MIN,      HUE_MAX))
            self.ui.time_on.setTime(config_time(d.get("on_hour"), d.get("on_min"), 19, 0))
            self.ui.time_off.setTime(config_time(d.get("off_hour"), d.get("off_min"), 6, 0))
            self.ui.check_auto.setChecked(bool(d.get("auto_schedule", False)))
            saved_disp = d.get("display", "")
            if saved_disp:
                idx = self.ui.combo.findText(saved_disp)
                if idx >= 0:
                    self.ui.combo.setCurrentIndex(idx)
            log.info("Settings loaded")
        except Exception as e:
            log.error("Load failed: %s — using defaults", e)

    def save_settings(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            data = {
                "bright":        self.ui.sl_bright.value(),
                "contrast":      self.ui.sl_contrast.value(),
                "gamma":         self.ui.sl_gamma.value(),   # was "g" — FIX
                "temp":          self.ui.sl_temp.value(),
                "red":           self.ui.sl_r.value(),
                "green":         self.ui.sl_g.value(),       # was "g" — FIX
                "blue":          self.ui.sl_b.value(),       # was "bb" — FIX
                "vib":           self.ui.sl_vib.value(),
                "hue":           self.ui.sl_hue.value(),
                "auto_schedule": self.ui.check_auto.isChecked(),
                "on_hour":       self.ui.time_on.time().hour(),
                "on_min":        self.ui.time_on.time().minute(),
                "off_hour":      self.ui.time_off.time().hour(),
                "off_min":       self.ui.time_off.time().minute(),
                "display":       self.ui.combo.currentText(),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error("Save failed: %s", e)

    def schedule_update(self):
        self._debounce.start()

    def _apply_startup_settings(self):
        if self.ui.check_auto.isChecked():
            self._check_auto_schedule(force=self._last_schedule_state is None)
        else:
            self.apply_settings()

    def apply_settings(self):
        self.save_settings()

        if not has_display_session():
            self.ui.status.set_warn("No graphical display session")
            log.warning("No DISPLAY or WAYLAND_DISPLAY set; skipping display command")
            return

        br   = clamp(self.ui.sl_bright.value()   / 100.0, 0.01, 1.0)
        temp = clamp(self.ui.sl_temp.value(),    TEMP_MIN, TEMP_MAX)
        con  = self.ui.sl_contrast.value()
        gam  = clamp(self.ui.sl_gamma.value()   / 100.0,  0.5, 2.0)

        rm   = clamp(self.ui.sl_r.value()        / 100.0, 0.1, 1.0)
        gm   = clamp(self.ui.sl_g.value()        / 100.0, 0.1, 1.0)
        bm   = clamp(self.ui.sl_b.value()        / 100.0, 0.1, 1.0)

        # FIX: contrast factor — 50 = neutral, >50 boosts, <50 reduces
        contrast_factor = 0.6 + (con - CONTRAST_MIN) / (CONTRAST_MAX - CONTRAST_MIN) * 0.9
        base_gamma = gam * contrast_factor

        # Saturation boost (FIX: does NOT modify brightness)
        vib = self.ui.sl_vib.value()
        if vib > 0:
            vf  = vib / 200.0
            max_ch = max(rm, gm, bm)
            rm = clamp(rm + (max_ch - rm) * vf, 0.1, 1.0)
            gm = clamp(gm + (max_ch - gm) * vf, 0.1, 1.0)
            bm = clamp(bm + (max_ch - bm) * vf, 0.1, 1.0)

        # Hue shift
        hue = self.ui.sl_hue.value()
        if hue != 0:
            angle = math.radians(hue)
            rm = clamp(rm * (1.0 + 0.15 * math.sin(angle)),          0.1, 1.0)
            gm = clamp(gm * (1.0 + 0.15 * math.sin(angle + 2.094)),  0.1, 1.0)
            bm = clamp(bm * (1.0 + 0.15 * math.sin(angle + 4.189)),  0.1, 1.0)

        # FIX: gamma per channel = base_gamma * channel_multiplier (not division)
        g_r = clamp(base_gamma * rm, 0.1, 5.0)
        g_g = clamp(base_gamma * gm, 0.1, 5.0)
        g_b = clamp(base_gamma * bm, 0.1, 5.0)

        monitor = self.ui.current_display()

        # Stop previous execution to keep it non-blocking and responsive
        if self.process.state() != QProcess.NotRunning:
            self._process_queue = []
            self.process.terminate()
            if not self.process.waitForFinished(100):
                self.process.kill()
                self.process.waitForFinished(250)

        # Store context for status bar updates in finished signal
        self._last_applied_info = (temp, br, gam)

        gamma_arg = f"{g_r:.3f}:{g_g:.3f}:{g_b:.3f}"
        commands = []

        if self.redshift_path:
            # redshift handles the normal 10-100 range. xrandr applies a
            # secondary factor only for 1-9% and resets that factor to 1.0
            # for normal brightness, so 80-100 still changes via redshift.
            redshift_br = clamp(br, 0.1, 1.0)
            cmd_args = [
                "-P", "-O", str(temp),
                "-b", f"{redshift_br:.3f}",
                "-g", gamma_arg,
            ]
            if monitor:
                try:
                    monitors = detect_displays()
                    if monitor in monitors:
                        crtc_idx = monitors.index(monitor)
                        cmd_args = ["-m", f"randr:crtc={crtc_idx}"] + cmd_args
                except Exception as e:
                    log.warning("Failed to determine CRTC for %s: %s", monitor, e)

            log.debug("Apply redshift: %s %s", self.redshift_path, cmd_args)
            commands.append((self.redshift_path, cmd_args, "redshift"))

            if self.xrandr_path:
                xrandr_factor = clamp(br / redshift_br, 0.01, 1.0)
                xrandr_args = self._build_xrandr_args(monitor, xrandr_factor)
                if xrandr_args:
                    log.debug("Apply xrandr brightness: %s %s",
                              self.xrandr_path, xrandr_args)
                    commands.append((self.xrandr_path, xrandr_args, "xrandr"))
            elif br < 0.1:
                log.warning("Brightness below 10%% requires xrandr; redshift will clamp it")

        elif self.xrandr_path:
            xrandr_args = self._build_xrandr_args(monitor, br, gamma_arg)
            if xrandr_args:
                log.debug("Apply xrandr: %s %s", self.xrandr_path, xrandr_args)
                commands.append((self.xrandr_path, xrandr_args, "xrandr"))
            else:
                self.ui.status.set_warn("No monitors detected")
        else:
            self.ui.status.set_warn("No redshift or xrandr available")
            log.warning("No display control tool found")
            return

        if commands:
            self._run_display_commands(commands)

    def _build_xrandr_args(self, monitor, brightness, gamma=None):
        outputs = [monitor] if monitor else detect_displays()
        if not outputs:
            return []

        args = []
        for output in outputs:
            args.extend(["--output", output, "--brightness", f"{brightness:.3f}"])
            if gamma:
                args.extend(["--gamma", gamma])
        return args

    def _run_display_commands(self, commands):
        self._process_queue = list(commands)
        self._apply_had_error = False
        self._start_next_display_process()

    def _start_next_display_process(self):
        if not self._process_queue:
            self._finish_apply_status()
            return

        program, args, label = self._process_queue.pop(0)
        self._current_process_label = label
        self.process.start(program, args)
        if not self.process.waitForStarted(500):
            err = self.process.errorString()
            self._apply_had_error = True
            log.warning("Failed to start %s (%s): %s", label, program, err)
            self._start_next_display_process()

    def _stop_display_process(self):
        self._process_queue = []
        if self.process.state() == QProcess.NotRunning:
            return
        self.process.terminate()
        if not self.process.waitForFinished(500):
            self.process.kill()
            self.process.waitForFinished(500)

    def _on_process_finished(self, exit_code, exit_status):
        if exit_code != 0 or exit_status != QProcess.NormalExit:
            err = self.process.readAllStandardError().data().decode().strip()
            log.warning("%s exited with code %d: %s",
                        self._current_process_label, exit_code, err)
            self._apply_had_error = True

        self._start_next_display_process()

    def _finish_apply_status(self):
        if self._apply_had_error:
            self.ui.status.set_warn("Some display settings failed")
            return
        if self._last_applied_info:
            temp, br, gam = self._last_applied_info
            self.ui.status.set_ok(f"{temp}K  {int(br*100)}%  γ={gam:.2f}")

    def _on_process_error(self, process_error):
        self._apply_had_error = True
        log.warning("Display command failed to start or run: %s (%s)",
                    self.process.errorString(), process_error)

    def on_schedule_toggled(self, checked):
        if checked:
            self._check_auto_schedule(force=True)
        else:
            self._last_schedule_state = None
            self.ui.clear_night_status()
            self.apply_settings()

    def _check_auto_schedule(self, force=False):
        if not self.ui.check_auto.isChecked():
            self._last_schedule_state = None
            return

        now   = datetime.datetime.now().time()
        t_on  = self.ui.time_on.time().toPyTime()
        t_off = self.ui.time_off.time().toPyTime()

        # FIX: correct overnight span logic
        if t_on <= t_off:
            is_night = t_on <= now < t_off
        else:
            is_night = now >= t_on or now < t_off

        # Only apply schedule preset if the state has transitioned or we force it
        if force or self._last_schedule_state != is_night:
            self._last_schedule_state = is_night
            if is_night:
                log.info("Schedule transition → night mode")
                self.ui.sl_temp.set_value(NIGHT_TEMP)
                self.ui.sl_bright.set_value(70)
                self.ui.set_night_status(True)
            else:
                log.info("Schedule transition → day mode")
                self.ui.sl_temp.set_value(DAY_TEMP)
                self.ui.sl_bright.set_value(BRIGHT_DEF)
                self.ui.set_night_status(False)
            self.apply_settings()

    def _init_tray(self):
        pix = QPixmap(64, 64)
        pix.fill(QColor("transparent"))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, 64, 64)
        grad.setColorAt(0.0, QColor("#00e5ff"))
        grad.setColorAt(0.5, QColor("#aa00ff"))
        grad.setColorAt(1.0, QColor("#ff4444"))
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        p.drawEllipse(4, 4, 56, 56)
        p.setBrush(QColor(10, 12, 18, 220))
        p.drawEllipse(16, 16, 32, 32)
        p.setBrush(QColor("white"))
        p.drawEllipse(28, 28, 8, 8)
        p.end()

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(pix))
        self.tray.setToolTip(f"{APP_NAME} — Click to open | Right-click for menu")
        self.tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu { background:#0e111a;color:#ccc;border:1px solid #2a2f3e;padding:4px; }
            QMenu::item { padding:6px 20px;border-radius:3px; }
            QMenu::item:selected { background:#00e5ff;color:#000; }
            QMenu::separator { background:#222;height:1px;margin:4px 8px; }
        """)
        a_show  = QAction("⬛  Open Panel", self)
        a_show.triggered.connect(self.ui.show_near_mouse)
        menu.addAction(a_show)
        a_day   = QAction("☀  Day Mode", self)
        a_day.triggered.connect(self.ui._set_day_mode)
        menu.addAction(a_day)
        a_night = QAction("🌙  Night Mode", self)
        a_night.triggered.connect(self.ui._set_night_mode)
        menu.addAction(a_night)
        menu.addSeparator()
        a_quit  = QAction("✕  Quit", self)
        a_quit.triggered.connect(self._quit_cleanly)
        menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.ui.isVisible():
                self.ui.hide()
            else:
                self.ui.show_near_mouse()

    def _quit_cleanly(self):
        log.info("Quit requested — restoring display defaults")
        if self.redshift_path:
            run_cmd([self.redshift_path, "-x"], silent=True)
        if self.xrandr_path:
            for m in detect_displays():
                run_cmd(
                    [self.xrandr_path, "--output", m,
                     "--brightness", "1.0", "--gamma", "1.0:1.0:1.0"],
                    silent=True
                )
        self.save_settings()
        QApplication.instance().quit()


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    if not has_display_session():
        print(
            "ERROR: No graphical display session detected. "
            "Start Kali Glass from X11/Wayland or set DISPLAY."
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    # Singleton lock
    sock = QLocalSocket()
    sock.connectToServer(LOCK_NAME)
    if sock.waitForConnected(500):
        print(f"{APP_NAME} is already running.")
        sys.exit(0)

    srv = QLocalServer()
    srv.removeServer(LOCK_NAME)
    if not srv.listen(LOCK_NAME):
        log.warning("Could not acquire singleton lock — continuing anyway")

    # FIX: Wait for tray with timeout — not an infinite blocking loop
    deadline = time.time() + 10
    while not QSystemTrayIcon.isSystemTrayAvailable() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.3)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("System tray unavailable after 10s — continuing without it")

    app.kali_glass_engine = DisplayEngine()
    ret = app.exec_()
    srv.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
