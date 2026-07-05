#!/usr/bin/env python3
# ============================================================
# KALI GLASS CONTROLLER v2.1
# A display control center for Kali Linux (X11)
# License: MIT
#
# FIXES in v2.1:
#   - xrandr-only backend path (no more redshift/xrandr conflicts)
#   - 300ms debounce to prevent slider-spam
#   - "latest wins" logic — never kills a running process; queues
#     only the newest pending settings and applies them after finish
#   - Brightness 100% = xrandr 1.0, 50% = 0.5, 5% = 0.05
#   - Contrast neutral at slider value 50 produces no change (gamma 1.0)
#   - RGB sliders affect red/green/blue gamma independently
#   - Wayland shows clear warning; silently skips display commands
#   - Startup diagnostic log: session type, DISPLAY, xrandr path, outputs
#   - Redshift is neutralized once before manual xrandr control if present
#   - "Test Backend" tray action for on-demand diagnostics
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
    QComboBox, QGraphicsDropShadowEffect, QMessageBox
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
APP_VERSION     = "2.1"
LOCK_NAME       = "kali-glass-single-instance-lock"
CONFIG_FILE     = os.path.expanduser(
    os.environ.get("KALI_GLASS_CONFIG", "~/.config/kali_glass/config.json")
)
CONFIG_DIR      = os.path.dirname(CONFIG_FILE)
LOG_FILE        = os.path.expanduser(
    os.environ.get("KALI_GLASS_LOG", "~/.config/kali_glass/kali_glass.log")
)

# Slider limits
BRIGHT_MIN, BRIGHT_MAX, BRIGHT_DEF   = 5, 100, 100
# Contrast: 50 = neutral (no change), <50 = less contrast, >50 = more contrast
CONTRAST_MIN, CONTRAST_MAX, CONTRAST_DEF = 1, 100, 50
# Gamma: 100 = neutral (1.0), 50 = 0.5, 200 = 2.0
GAMMA_MIN, GAMMA_MAX, GAMMA_DEF      = 50, 200, 100
TEMP_MIN, TEMP_MAX, TEMP_DEF         = 1000, 6500, 6500
RGB_MIN, RGB_MAX, RGB_DEF            = 10, 100, 100
VIB_MIN, VIB_MAX, VIB_DEF            = 0, 100, 0
HUE_MIN, HUE_MAX, HUE_DEF            = 0, 360, 0

# Increased debounce so slider drag doesn't spam commands
DEBOUNCE_MS    = 300    # slider debounce delay (ms)
SCHEDULE_MS    = 30000  # schedule check interval
CMD_TIMEOUT    = 5      # subprocess timeout seconds
STARTUP_APPLY_DELAYS_MS = (500, 3000, 8000)
NIGHT_TEMP     = 3200
DAY_TEMP       = 6500

# xrandr gamma clamping — safe range
GAMMA_XRANDR_MIN = 0.3
GAMMA_XRANDR_MAX = 3.0

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


def get_display_env(env=None):
    env = os.environ if env is None else env
    return env.get("DISPLAY", "")


def has_display_session(env=None):
    env = os.environ if env is None else env
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def is_wayland(env=None):
    env = os.environ if env is None else env
    return bool(
        env.get("WAYLAND_DISPLAY") or
        env.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def is_x11(env=None):
    env = os.environ if env is None else env
    return bool(env.get("DISPLAY")) and not is_wayland(env)


def display_unavailable_reason(env=None, xrandr_path=None):
    env = os.environ if env is None else env
    if is_wayland(env):
        return "Wayland detected — xrandr software brightness requires X11."
    if not get_display_env(env):
        return "No graphical display session (DISPLAY not set)."
    if not xrandr_path:
        return "xrandr not found — install x11-xserver-utils."
    return ""


def parse_xrandr_outputs(query_output):
    monitors = []
    for line in query_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "connected":
            monitors.append(parts[0])
    return monitors


def backlight_devices(backlight_dir="/sys/class/backlight"):
    try:
        return sorted(
            entry.name for entry in os.scandir(backlight_dir)
            if entry.is_dir() or entry.is_symlink()
        )
    except OSError:
        return []


def brightnessctl_available(brightnessctl_path=None, backlight_dir="/sys/class/backlight"):
    brightnessctl_path = brightnessctl_path or shutil.which("brightnessctl")
    return bool(brightnessctl_path and backlight_devices(backlight_dir))


def _normalize_cmd(cmd):
    if isinstance(cmd, (list, tuple)):
        return [str(part) for part in cmd]
    return shlex.split(str(cmd))


def run_cmd(cmd, timeout=CMD_TIMEOUT, silent=False):
    env = os.environ.copy()
    args = _normalize_cmd(cmd)
    display_cmd = shlex.join(args)
    proc = None
    try:
        with subprocess.Popen(
            args, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env
        ) as proc:
            if not silent:
                log.info("Command started pid=%s: %s", proc.pid, display_cmd)
            stdout, stderr = proc.communicate(timeout=timeout)
            ok = proc.returncode == 0
            if not silent:
                log.info(
                    "Command finished pid=%s exit=%s stdout=%r stderr=%r",
                    proc.pid, proc.returncode, stdout.strip(), stderr.strip()
                )
            elif not ok:
                log.debug("cmd non-zero [%d]: %s | %s",
                          proc.returncode, display_cmd[:200], stderr.strip())
            return ok, stdout, stderr
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
            proc.communicate()
        log.warning("Command timed out (%ds): %s", timeout, display_cmd[:200])
        return False, "", "timeout"
    except Exception as e:
        if not silent:
            log.error("Command error: %s | %s", display_cmd[:200], e)
        return False, "", str(e)


def detect_displays():
    """Return list of connected output names via xrandr --query."""
    xrandr_path = shutil.which("xrandr")
    if not xrandr_path:
        log.warning("xrandr not found — cannot detect displays")
        return []
    if not get_display_env():
        log.debug("DISPLAY not set; skipping xrandr display detection")
        return []
    ok, out, err = run_cmd([xrandr_path, "--query"], silent=True)
    if not ok or not out.strip():
        log.warning("xrandr --query failed: %s", err.strip())
        return []
    return parse_xrandr_outputs(out)


def config_time(hour, minute, default_hour, default_minute):
    try:
        hour = int(hour)
        minute = int(minute)
    except (TypeError, ValueError):
        return QTime(default_hour, default_minute)
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return QTime(hour, minute)
    return QTime(default_hour, default_minute)


def temp_to_gamma(kelvin):
    """
    Convert color temperature (K) to approximate RGB gamma offsets for xrandr.
    Returns (r_factor, g_factor, b_factor) all near 1.0 at 6500K,
    shifting warm (red↑, blue↓) at lower temps.
    This keeps color temperature inside the xrandr gamma path.
    """
    k = clamp(kelvin, 1000, 6500)
    # Linear interpolation from 6500K (neutral) to 1000K (warm orange)
    t = (6500 - k) / 5500.0   # 0.0 at 6500K, 1.0 at 1000K

    r = clamp(1.0 + t * 0.0, 0.5, 1.0)           # red stays at 1.0
    g = clamp(1.0 - t * 0.15, 0.5, 1.0)           # green drops slightly
    b = clamp(1.0 - t * 0.55, 0.1, 1.0)           # blue drops more

    return r, g, b


# ============================================================
# SETTINGS SNAPSHOT
# ============================================================

class DisplaySettings:
    """Immutable snapshot of all slider values at a point in time."""
    __slots__ = (
        "brightness", "contrast", "gamma",
        "temp", "r", "g", "b", "vib", "hue", "monitor", "reset"
    )

    def __init__(self, brightness, contrast, gamma,
                 temp, r, g, b, vib, hue, monitor, reset=False):
        self.brightness = brightness
        self.contrast   = contrast
        self.gamma      = gamma
        self.temp       = temp
        self.r          = r
        self.g          = g
        self.b          = b
        self.vib        = vib
        self.hue        = hue
        self.monitor    = monitor
        self.reset      = reset


# ============================================================
# CUSTOM WIDGETS
# ============================================================

class NeonSlider(QWidget):
    changed = pyqtSignal()
    released = pyqtSignal()

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
        self.slider.sliderReleased.connect(self.released.emit)
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
        self.resize(340, 750)

    def _connect_slider(self, slider):
        slider.changed.connect(self._engine.schedule_update)
        slider.released.connect(self._engine.flush_update)

    def _build_ui(self, L):
        # ── Header ────────────────────────────────────────
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

        # ── Wayland warning ───────────────────────────────
        if is_wayland():
            w = QLabel(
                "⚠  Wayland detected — xrandr does NOT work on Wayland.\n"
                "   Log out and choose an X11 session to use this app."
            )
            w.setStyleSheet(
                "color:#ff6600;font-size:9px;background:rgba(255,100,0,15);"
                "padding:6px;border-radius:4px;border:1px solid rgba(255,100,0,45);"
            )
            w.setWordWrap(True)
            L.addWidget(w)
        elif not get_display_env():
            w = QLabel("⚠  DISPLAY not set — display control unavailable.")
            w.setStyleSheet(
                "color:#ffaa00;font-size:9px;background:rgba(255,170,0,15);"
                "padding:4px;border-radius:4px;"
            )
            w.setWordWrap(True)
            L.addWidget(w)

        # ── Display selector ──────────────────────────────
        L.addWidget(SectionHeader("▸  DISPLAY TARGET"))
        dr = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setToolTip("Select which monitor to control")
        self._populate_displays()
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

        L.addSpacing(2)
        L.addWidget(SectionHeader("▸  BRIGHTNESS & DISPLAY"))

        self.sl_bright = NeonSlider(
            "Brightness", BRIGHT_MIN, BRIGHT_MAX, BRIGHT_DEF, "#e8e8e8", "%",
            "Screen brightness (5–100%)  →  xrandr 0.05–1.0"
        )
        self._connect_slider(self.sl_bright)
        L.addWidget(self.sl_bright)

        self.sl_contrast = NeonSlider(
            "Contrast", CONTRAST_MIN, CONTRAST_MAX, CONTRAST_DEF, "#00d4f5", "",
            "Contrast (50 = neutral, >50 = more contrast, <50 = less)"
        )
        self._connect_slider(self.sl_contrast)
        L.addWidget(self.sl_contrast)

        self.sl_gamma = NeonSlider(
            "Gamma", GAMMA_MIN, GAMMA_MAX, GAMMA_DEF, "#7799ff", "",
            "Gamma multiplier (100 = neutral = xrandr 1.0)"
        )
        self._connect_slider(self.sl_gamma)
        L.addWidget(self.sl_gamma)

        L.addSpacing(2)
        L.addWidget(SectionHeader("▸  COLOR TEMPERATURE"))

        self.sl_temp = NeonSlider(
            "Color Temperature", TEMP_MIN, TEMP_MAX, TEMP_DEF, "#ffaa00", "K",
            "Color warmth: 6500K = daylight | 1000K = warm orange\n"
            "Applied as xrandr gamma offsets (no redshift dependency)"
        )
        self.sl_temp.slider.setInvertedAppearance(True)
        self._connect_slider(self.sl_temp)
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

        self.sl_r = NeonSlider("Red",   RGB_MIN, RGB_MAX, RGB_DEF, "#ff4455", "%",
                               "Red gamma channel (100% = no change)")
        self._connect_slider(self.sl_r)
        L.addWidget(self.sl_r)

        self.sl_g = NeonSlider("Green", RGB_MIN, RGB_MAX, RGB_DEF, "#44ff88", "%",
                               "Green gamma channel (100% = no change)")
        self._connect_slider(self.sl_g)
        L.addWidget(self.sl_g)

        self.sl_b = NeonSlider("Blue",  RGB_MIN, RGB_MAX, RGB_DEF, "#4488ff", "%",
                               "Blue gamma channel (100% = no change)")
        self._connect_slider(self.sl_b)
        L.addWidget(self.sl_b)

        L.addSpacing(2)
        L.addWidget(SectionHeader("▸  ENHANCEMENTS"))

        self.sl_vib = NeonSlider(
            "Saturation Boost", VIB_MIN, VIB_MAX, VIB_DEF, "#ff00cc", "%",
            "Boost color saturation (0 = none)"
        )
        self._connect_slider(self.sl_vib)
        L.addWidget(self.sl_vib)

        self.sl_hue = NeonSlider(
            "Hue Shift", HUE_MIN, HUE_MAX, HUE_DEF, "#aa44ff", "°",
            "Rotate color hue (0 = no shift)"
        )
        self._connect_slider(self.sl_hue)
        L.addWidget(self.sl_hue)

        L.addSpacing(6)
        br = QHBoxLayout()
        br.setSpacing(8)
        self.btn_reset = QPushButton("☀  Reset")
        self.btn_reset.setObjectName("ResetBtn")
        self.btn_reset.setToolTip("Reset display to 100% brightness and neutral gamma")
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
            if not is_wayland() and get_display_env():
                log.warning("No connected outputs detected by xrandr --query")
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
        self._engine.reset_display()

    def _set_night_mode(self):
        self.sl_temp.set_value(NIGHT_TEMP)
        self.sl_bright.set_value(70)
        self._engine.apply_settings()

    def current_display(self):
        txt = self.combo.currentText()
        return None if (not txt or "All Displays" in txt) else txt

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
    """
    Manages all display-setting logic.

    Anti-flicker design
    -------------------
    * One QProcess slot handles one xrandr command at a time.
    * While a command is running we do NOT kill it.
    * We store only the *newest* pending settings snapshot.
    * When the running command finishes we apply the pending snapshot
      (if any) and clear it.  Old intermediate settings are dropped.
    * The debounce timer (DEBOUNCE_MS = 300 ms) already batches rapid
      slider changes before any command is issued.
    """

    def __init__(self):
        super().__init__()

        self.xrandr_path  = shutil.which("xrandr")
        self.redshift_path = shutil.which("redshift")
        self.brightnessctl_path = shutil.which("brightnessctl")
        self.backlight_names = backlight_devices()

        # QProcess for asynchronous, non-blocking xrandr calls
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.errorOccurred.connect(self._on_proc_error)

        # "Latest wins" state
        self._pending_settings = None   # newest settings waiting to run
        self._proc_busy        = False  # True while xrandr is running
        self._last_cmd_str     = ""     # for diagnostics
        self._last_successful_cmd_str = ""

        self._last_schedule_state = None
        self._last_applied_info   = None
        self._apply_had_error     = False
        self._redshift_neutralized = False

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._stop_proc_cleanly)

        self.ui = NeonPopup(self)

        # Debounce timer — slider changes collect here before firing
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self.apply_settings)

        self._sched_timer = QTimer(self)
        self._sched_timer.timeout.connect(self._check_auto_schedule)
        self._sched_timer.start(SCHEDULE_MS)

        self._run_startup_diagnostics()
        self.load_settings()
        self._init_tray()

        self.ui.check_auto.toggled.connect(self.on_schedule_toggled)

        for delay_ms in STARTUP_APPLY_DELAYS_MS:
            QTimer.singleShot(delay_ms, self._apply_startup_settings)

        log.info("%s v%s started", APP_NAME, APP_VERSION)

    # ----------------------------------------------------------
    # Diagnostics
    # ----------------------------------------------------------

    def _run_startup_diagnostics(self):
        """Log environment info useful for debugging display issues."""
        session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
        display_val  = os.environ.get("DISPLAY", "(not set)")
        wayland_val  = os.environ.get("WAYLAND_DISPLAY", "(not set)")
        xrandr_path  = self.xrandr_path or "(not found)"
        redshift_path = self.redshift_path or "(not found)"
        brightnessctl_path = self.brightnessctl_path or "(not found)"
        backlights = self.backlight_names or []

        log.info("=== STARTUP DIAGNOSTICS ===")
        log.info("  Session type    : %s", session_type)
        log.info("  DISPLAY         : %s", display_val)
        log.info("  WAYLAND_DISPLAY : %s", wayland_val)
        log.info("  xrandr path     : %s", xrandr_path)
        log.info("  redshift path   : %s", redshift_path)
        log.info("  brightnessctl   : %s", brightnessctl_path)
        log.info("  backlight devs  : %s", ", ".join(backlights) if backlights else "(none)")

        if is_wayland():
            log.warning("  *** Wayland session detected — xrandr will NOT work ***")
            log.warning("  *** Log out and select an X11 session for full control ***")
        elif not get_display_env():
            log.warning("  *** DISPLAY variable not set — cannot run xrandr ***")
        else:
            log.info("  Backend         : xrandr (primary)")
            if brightnessctl_available(self.brightnessctl_path):
                log.info("  Backlight fallback: available")
            else:
                log.info("  Backlight fallback: unavailable; using xrandr software brightness")
            outputs = detect_displays()
            if outputs:
                log.info("  Detected outputs: %s", ", ".join(outputs))
            else:
                log.warning("  No connected outputs detected by xrandr --query")
        log.info("=== END DIAGNOSTICS ===")

    def run_backend_diagnostics(self):
        """On-demand diagnostics (called from tray menu)."""
        self._run_startup_diagnostics()
        outputs = detect_displays()
        session = os.environ.get("XDG_SESSION_TYPE", "unknown")
        display = os.environ.get("DISPLAY", "not set")
        lines = [
            f"Session type : {session}",
            f"DISPLAY      : {display}",
            f"xrandr       : {self.xrandr_path or 'not found'}",
            f"redshift     : {self.redshift_path or 'not found'}",
            f"brightnessctl: {self.brightnessctl_path or 'not found'}",
            f"Backlights   : {', '.join(self.backlight_names) if self.backlight_names else 'none'}",
            f"Outputs      : {', '.join(outputs) if outputs else 'none detected'}",
            "Backend      : xrandr (primary)",
            f"Last command : {self._last_cmd_str or 'none'}",
            "",
            "See log for full details:",
            LOG_FILE,
        ]
        QMessageBox.information(None, "Kali Glass — Backend Diagnostics",
                                "\n".join(lines))

    # ----------------------------------------------------------
    # Settings persistence
    # ----------------------------------------------------------

    def load_settings(self):
        if not os.path.exists(CONFIG_FILE):
            log.info("No config — using defaults")
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.ui.sl_bright.set_value(  clamp(d.get("bright",   BRIGHT_DEF),   BRIGHT_MIN,   BRIGHT_MAX))
            self.ui.sl_contrast.set_value(clamp(d.get("contrast", CONTRAST_DEF), CONTRAST_MIN, CONTRAST_MAX))
            self.ui.sl_gamma.set_value(   clamp(d.get("gamma",    GAMMA_DEF),    GAMMA_MIN,    GAMMA_MAX))
            self.ui.sl_temp.set_value(    clamp(d.get("temp",     TEMP_DEF),     TEMP_MIN,     TEMP_MAX))
            self.ui.sl_r.set_value(       clamp(d.get("red",      RGB_DEF),      RGB_MIN,      RGB_MAX))
            self.ui.sl_g.set_value(       clamp(d.get("green",    RGB_DEF),      RGB_MIN,      RGB_MAX))
            self.ui.sl_b.set_value(       clamp(d.get("blue",     RGB_DEF),      RGB_MIN,      RGB_MAX))
            self.ui.sl_vib.set_value(     clamp(d.get("vib",      VIB_DEF),      VIB_MIN,      VIB_MAX))
            self.ui.sl_hue.set_value(     clamp(d.get("hue",      HUE_DEF),      HUE_MIN,      HUE_MAX))
            self.ui.time_on.setTime(config_time(d.get("on_hour"),  d.get("on_min"),  19, 0))
            self.ui.time_off.setTime(config_time(d.get("off_hour"), d.get("off_min"), 6,  0))
            self.ui.check_auto.setChecked(bool(d.get("auto_schedule", False)))
            saved_disp = d.get("display", "")
            if saved_disp:
                idx = self.ui.combo.findText(saved_disp)
                if idx >= 0:
                    self.ui.combo.setCurrentIndex(idx)
            log.info("Settings loaded from %s", CONFIG_FILE)
        except Exception as e:
            log.error("Load failed: %s — using defaults", e)

    def save_settings(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            data = {
                "bright":        self.ui.sl_bright.value(),
                "contrast":      self.ui.sl_contrast.value(),
                "gamma":         self.ui.sl_gamma.value(),
                "temp":          self.ui.sl_temp.value(),
                "red":           self.ui.sl_r.value(),
                "green":         self.ui.sl_g.value(),
                "blue":          self.ui.sl_b.value(),
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

    # ----------------------------------------------------------
    # Debounce & apply entry points
    # ----------------------------------------------------------

    def schedule_update(self):
        """Called on every slider valueChanged — restarts debounce timer."""
        self._debounce.start()

    def flush_update(self):
        """Apply immediately when a slider is released."""
        if self._debounce.isActive():
            self._debounce.stop()
        self.apply_settings()

    def _apply_startup_settings(self):
        if self.ui.check_auto.isChecked():
            self._check_auto_schedule(force=self._last_schedule_state is None)
        else:
            self.apply_settings()

    def _settings_snapshot(self, reset=False):
        return DisplaySettings(
            brightness = self.ui.sl_bright.value(),
            contrast   = self.ui.sl_contrast.value(),
            gamma      = self.ui.sl_gamma.value(),
            temp       = self.ui.sl_temp.value(),
            r          = self.ui.sl_r.value(),
            g          = self.ui.sl_g.value(),
            b          = self.ui.sl_b.value(),
            vib        = self.ui.sl_vib.value(),
            hue        = self.ui.sl_hue.value(),
            monitor    = self.ui.current_display(),
            reset      = reset,
        )

    def reset_display(self):
        """Reset selected output(s) to xrandr brightness 1.0 and gamma 1:1:1."""
        self.save_settings()
        reason = display_unavailable_reason(xrandr_path=self.xrandr_path)
        if reason:
            self.ui.status.set_warn(reason)
            log.warning("%s", reason)
            return
        self._neutralize_redshift_once()
        self._queue_or_dispatch(self._settings_snapshot(reset=True))

    def apply_settings(self):
        """
        Public entry point.  Captures a settings snapshot, saves config,
        and triggers the "latest wins" dispatch.
        """
        self.save_settings()

        reason = display_unavailable_reason(xrandr_path=self.xrandr_path)
        if reason:
            self.ui.status.set_warn(reason)
            log.warning("%s", reason)
            return

        self._neutralize_redshift_once()
        self._queue_or_dispatch(self._settings_snapshot())

    def _queue_or_dispatch(self, snap):
        """Dispatch immediately when idle, otherwise keep only the newest snapshot."""
        if self._proc_busy:
            self._pending_settings = snap
            log.debug("xrandr busy — queued latest settings snapshot")
            return False

        self._dispatch(snap)
        return True

    def _redshift_process_running(self):
        pgrep_path = shutil.which("pgrep")
        if not pgrep_path:
            return False
        ok, out, _ = run_cmd([pgrep_path, "-x", "redshift"], silent=True)
        return bool(ok and out.strip())

    def _neutralize_redshift_once(self):
        if self._redshift_neutralized:
            return
        self._redshift_neutralized = True

        if not self.redshift_path:
            log.info("redshift not found; no external color process to neutralize")
            return

        was_running = self._redshift_process_running()
        ok, out, err = run_cmd([self.redshift_path, "-x"], silent=False)
        log.info(
            "redshift neutralize once running=%s ok=%s stdout=%r stderr=%r",
            was_running, ok, out.strip(), err.strip()
        )
        if was_running:
            log.warning(
                "External redshift process was active; neutralized before xrandr control"
            )

    # ----------------------------------------------------------
    # Settings → xrandr gamma computation
    # ----------------------------------------------------------

    @staticmethod
    def _compute_gamma(snap):
        """
        Compute (brightness_xrandr, gamma_str) from a DisplaySettings snapshot.

        brightness_xrandr : float  0.05–1.0  (xrandr --brightness)
        gamma_str         : str    "R:G:B"   (xrandr --gamma)

        Rules
        -----
        * brightness 100 → xrandr 1.0, brightness 50 → 0.5, brightness 5 → 0.05
        * contrast 50 → no change (factor 1.0)
        * gamma slider 100 → multiplier 1.0
        * RGB sliders 100 → no channel shift
        * temperature modifies channel ratios (no redshift needed)
        """
        br_xrandr = clamp(snap.brightness / 100.0, 0.05, 1.0)

        # Gamma slider: 100 → 1.0, 50 → 0.5, 200 → 2.0
        gam = clamp(snap.gamma / 100.0, GAMMA_XRANDR_MIN, GAMMA_XRANDR_MAX)

        # Contrast: 50 = neutral (1.0), 1 ≈ 0.51, 100 = 1.5
        # 0.5 + contrast/100 → at 50: 0.5+0.5=1.0 (exact neutral) ✓
        contrast_factor = 0.5 + snap.contrast / 100.0

        base_gamma = gam * contrast_factor

        # RGB channel multipliers: 100% → 1.0, 10% → 0.1
        rm = clamp(snap.r / 100.0, 0.1, 1.0)
        gm = clamp(snap.g / 100.0, 0.1, 1.0)
        bm = clamp(snap.b / 100.0, 0.1, 1.0)

        # Color temperature — shift channel ratios
        t_r, t_g, t_b = temp_to_gamma(snap.temp)
        rm = clamp(rm * t_r, 0.1, 1.0)
        gm = clamp(gm * t_g, 0.1, 1.0)
        bm = clamp(bm * t_b, 0.1, 1.0)

        # Saturation boost
        if snap.vib > 0:
            vf      = snap.vib / 200.0
            max_ch  = max(rm, gm, bm)
            rm = clamp(rm + (max_ch - rm) * vf, 0.05, 1.0)
            gm = clamp(gm + (max_ch - gm) * vf, 0.05, 1.0)
            bm = clamp(bm + (max_ch - bm) * vf, 0.05, 1.0)

        # Hue shift
        if snap.hue != 0:
            angle = math.radians(snap.hue)
            rm = clamp(rm * (1.0 + 0.15 * math.sin(angle)),          0.05, 1.0)
            gm = clamp(gm * (1.0 + 0.15 * math.sin(angle + 2.094)),  0.05, 1.0)
            bm = clamp(bm * (1.0 + 0.15 * math.sin(angle + 4.189)),  0.05, 1.0)

        # Final per-channel gamma (clamped to safe xrandr range)
        g_r = clamp(base_gamma * rm, GAMMA_XRANDR_MIN, GAMMA_XRANDR_MAX)
        g_g = clamp(base_gamma * gm, GAMMA_XRANDR_MIN, GAMMA_XRANDR_MAX)
        g_b = clamp(base_gamma * bm, GAMMA_XRANDR_MIN, GAMMA_XRANDR_MAX)

        gamma_str = f"{g_r:.3f}:{g_g:.3f}:{g_b:.3f}"
        return br_xrandr, gamma_str

    # ----------------------------------------------------------
    # xrandr command building
    # ----------------------------------------------------------

    def _build_xrandr_args(self, outputs, brightness, gamma_str):
        """
        Build xrandr argument list that applies brightness + gamma in one
        command for all requested outputs.  This is the single stable path.
        """
        args = []
        for output in outputs:
            args += [
                "--output", output,
                "--brightness", f"{brightness:.3f}",
                "--gamma", gamma_str,
            ]
        return args

    def _build_reset_xrandr_args(self, outputs):
        """Build the neutral reset command requested by the UI reset button."""
        args = []
        for output in outputs:
            args += [
                "--output", output,
                "--brightness", "1.0",
                "--gamma", "1:1:1",
            ]
        return args

    # ----------------------------------------------------------
    # Process dispatch (latest-wins)
    # ----------------------------------------------------------

    def _dispatch(self, snap):
        """Launch xrandr with the given settings snapshot."""
        outputs = ([snap.monitor] if snap.monitor else detect_displays())
        if not outputs:
            self.ui.status.set_warn("No displays detected — check xrandr --query")
            log.warning("No connected xrandr outputs; nothing to apply")
            return

        if snap.reset:
            br_xrandr, gamma_str = 1.0, "1:1:1"
            args = self._build_reset_xrandr_args(outputs)
        else:
            br_xrandr, gamma_str = self._compute_gamma(snap)
            args = self._build_xrandr_args(outputs, br_xrandr, gamma_str)

        cmd_str = shlex.join([self.xrandr_path] + args)
        self._last_cmd_str = cmd_str
        selected = snap.monitor or "All Displays"
        self._last_applied_info = (snap.temp, br_xrandr, snap.gamma / 100.0)

        if cmd_str == self._last_successful_cmd_str:
            log.info("Skipping unchanged xrandr command: %s", cmd_str)
            self._finish_apply_status()
            return

        log.info("Selected output: %s", selected)
        log.info("Connected outputs for command: %s", ", ".join(outputs))
        log.info("xrandr: %s", cmd_str)

        self._apply_had_error   = False
        self._proc_busy         = True

        self._proc.start(self.xrandr_path, args)
        if not self._proc.waitForStarted(1000):
            err = self._proc.errorString()
            log.error("Failed to start xrandr: %s", err)
            self.ui.status.set_err(f"xrandr failed to start: {err}")
            self._proc_busy = False
            self._apply_pending()
        else:
            log.info("xrandr process PID: %s", self._proc.processId())

    def _apply_pending(self):
        """If there is a pending settings snapshot, dispatch it now."""
        if self._pending_settings is not None:
            snap = self._pending_settings
            self._pending_settings = None
            self._dispatch(snap)

    def _on_proc_finished(self, exit_code, exit_status):
        self._proc_busy = False
        stdout = bytes(self._proc.readAllStandardOutput()).decode(errors="replace").strip()
        stderr = bytes(self._proc.readAllStandardError()).decode(errors="replace").strip()
        log.info(
            "xrandr finished exit=%s status=%s stdout=%r stderr=%r",
            exit_code, exit_status, stdout, stderr
        )

        if exit_code != 0 or exit_status != QProcess.NormalExit:
            log.warning("xrandr exited %d: %s", exit_code, stderr)
            self._apply_had_error = True
            self.ui.status.set_warn(f"xrandr error (code {exit_code})")
            log.warning("Last command: %s", self._last_cmd_str)
        else:
            self._last_successful_cmd_str = self._last_cmd_str
            self._finish_apply_status()

        self._apply_pending()

    def _on_proc_error(self, process_error):
        self._proc_busy = False
        self._apply_had_error = True
        log.error("xrandr process error %s: %s", process_error,
                  self._proc.errorString())
        log.error("Last command: %s", self._last_cmd_str)
        self._apply_pending()

    def _finish_apply_status(self):
        if self._apply_had_error:
            self.ui.status.set_warn("Some display settings failed")
            return
        if self._last_applied_info:
            temp, br, gam = self._last_applied_info
            self.ui.status.set_ok(f"{temp}K  {int(br * 100)}%  γ={gam:.2f}")

    def _stop_proc_cleanly(self):
        self._pending_settings = None
        if self._proc.state() != QProcess.NotRunning:
            self._proc.terminate()
            if not self._proc.waitForFinished(500):
                self._proc.kill()
                self._proc.waitForFinished(300)

    # ----------------------------------------------------------
    # Schedule
    # ----------------------------------------------------------

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

        # Correct overnight span logic
        if t_on <= t_off:
            is_night = t_on <= now < t_off
        else:
            is_night = now >= t_on or now < t_off

        if force or self._last_schedule_state != is_night:
            self._last_schedule_state = is_night
            if is_night:
                log.info("Schedule → night mode")
                self.ui.sl_temp.set_value(NIGHT_TEMP)
                self.ui.sl_bright.set_value(70)
                self.ui.set_night_status(True)
            else:
                log.info("Schedule → day mode")
                self.ui.sl_temp.set_value(DAY_TEMP)
                self.ui.sl_bright.set_value(BRIGHT_DEF)
                self.ui.set_night_status(False)
            self.apply_settings()

    # ----------------------------------------------------------
    # Tray
    # ----------------------------------------------------------

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
        a_diag  = QAction("🔍  Test Backend", self)
        a_diag.triggered.connect(self.run_backend_diagnostics)
        menu.addAction(a_diag)
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
        log.info("Quit requested — keeping current display settings")
        # Cancel any pending actions
        self._pending_settings = None
        self._stop_proc_cleanly()

        self.save_settings()
        QApplication.instance().quit()


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    if not has_display_session():
        print(
            "ERROR: No graphical display session detected. "
            "Start Kali Glass from X11 or set DISPLAY."
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

    # Wait for tray with timeout
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
