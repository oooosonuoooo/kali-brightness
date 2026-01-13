#!/usr/bin/env python3
# KALI GLASS CONTROLLER - GITHUB EDITION
# License: MIT

import sys
import os
import subprocess
import json
import shutil
import time
import math
import datetime
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QWidget, 
                             QVBoxLayout, QHBoxLayout, QLabel, QSlider, 
                             QPushButton, QFrame, QAction, QCheckBox, QTimeEdit, 
                             QComboBox, QGraphicsDropShadowEffect)
from PyQt5.QtCore import Qt, QTimer, QTime
from PyQt5.QtGui import QIcon, QPainter, QPixmap, QColor, QCursor, QLinearGradient
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

# --- CONFIGURATION ---
os.environ["DISPLAY"] = ":0"
CONFIG_FILE = os.path.expanduser("~/.config/kali_glass_config.json")
LOCK_NAME = "kali-glass-single-instance-lock"

class NeonSlider(QWidget):
    """Custom Slider Widget with Neon styling"""
    def __init__(self, name, min_val, max_val, init_val, color_hex, parent_callback, suffix=""):
        super().__init__()
        self.callback = parent_callback
        self.suffix = suffix
        
        layout = QVBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(0, 5, 0, 5)
        
        row = QHBoxLayout()
        self.lbl_name = QLabel(name.upper())
        self.lbl_name.setStyleSheet(f"color: {color_hex}; font-size: 9px; font-weight: bold; letter-spacing: 1px;")
        
        self.lbl_val = QLabel(f"{init_val}{suffix}")
        self.lbl_val.setStyleSheet("color: white; font-weight: bold; font-size: 10px;")
        self.lbl_val.setAlignment(Qt.AlignRight)
        
        row.addWidget(self.lbl_name)
        row.addWidget(self.lbl_val)
        layout.addLayout(row)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(int(init_val))
        self.slider.valueChanged.connect(self.on_change)
        
        # CSS Styling for the slider
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height: 4px; background: #333; border-radius: 2px; }}
            QSlider::handle:horizontal {{ 
                background: {color_hex}; width: 14px; margin: -5px 0; border-radius: 7px; 
                border: 1px solid white; 
            }}
            QSlider::sub-page:horizontal {{ background: {color_hex}; border-radius: 2px; }}
        """)
        
        layout.addWidget(self.slider)
        self.setLayout(layout)

    def on_change(self, val):
        self.lbl_val.setText(f"{val}{self.suffix}")
        self.callback()

    def set_value(self, val):
        self.slider.setValue(int(val))
        self.lbl_val.setText(f"{val}{self.suffix}")

class NeonPopup(QWidget):
    """Main Floating UI Window"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Main Window Style
        self.setStyleSheet("""
            QWidget#MainFrame { 
                background-color: rgba(10, 12, 18, 240); 
                border: 1px solid #555; 
                border-radius: 12px;
            }
            QLabel { font-family: sans-serif; }
            QCheckBox { color: #aaa; font-size: 11px; spacing: 5px; }
            QCheckBox::indicator { width: 13px; height: 13px; border-radius: 3px; border: 1px solid #555; }
            QCheckBox::indicator:checked { background-color: #00e5ff; border: 1px solid #00e5ff; }
            
            QComboBox { 
                background: #222; color: #00e5ff; border: 1px solid #444; 
                padding: 4px; font-size: 10px; border-radius: 4px;
            }
            
            QTimeEdit {
                background: #222; color: #00e5ff; border: 1px solid #444; 
                border-radius: 4px; padding: 2px; font-weight: bold; font-size: 11px;
            }
            QTimeEdit::up-button, QTimeEdit::down-button { width: 0px; }
            
            QPushButton#DayBtn {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffaa00, stop:1 #ffdd55);
                color: black; font-weight: bold; border-radius: 5px; padding: 5px; font-size: 10px;
            }
            QPushButton#DayBtn:hover { background-color: #ffeebb; }
            
            QPushButton#CloseBtn { background: transparent; color: #888; font-size: 16px; border: none; font-weight: bold; }
            QPushButton#CloseBtn:hover { color: #ff5555; }
        """)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.frame = QFrame()
        self.frame.setObjectName("MainFrame")
        
        # Drop Shadow for "Glass" effect
        try:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(25)
            shadow.setColor(QColor(0, 229, 255, 50))
            shadow.setOffset(0, 0)
            self.frame.setGraphicsEffect(shadow)
        except: pass

        self.layout = QVBoxLayout(self.frame)
        self.layout.setContentsMargins(20, 15, 20, 20)
        self.layout.setSpacing(8)

        # Header
        top_row = QHBoxLayout()
        title = QLabel("KALI GLASS")
        title.setStyleSheet("color: #00e5ff; font-weight: bold; letter-spacing: 2px; font-size: 11px;")
        close_btn = QPushButton("×")
        close_btn.setObjectName("CloseBtn")
        close_btn.clicked.connect(self.hide)
        top_row.addWidget(title)
        top_row.addStretch()
        top_row.addWidget(close_btn)
        self.layout.addLayout(top_row)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: #444; height: 1px; border: none;")
        self.layout.addWidget(line)

        # Display Selector
        self.layout.addWidget(QLabel("Target Display:"))
        self.combo = QComboBox()
        self.detect_displays()
        self.layout.addWidget(self.combo)
        self.layout.addSpacing(5)

        self.cb = self.trigger_update

        # Essential Sliders
        self.sl_bright = NeonSlider("Brightness", 10, 100, 100, "#ffffff", self.cb, "%")
        self.layout.addWidget(self.sl_bright)
        
        self.sl_contrast = NeonSlider("Contrast", 10, 100, 50, "#00e5ff", self.cb)
        self.layout.addWidget(self.sl_contrast)
        
        self.sl_gamma = NeonSlider("Gamma", 50, 200, 100, "#00e5ff", self.cb)
        self.layout.addWidget(self.sl_gamma)

        # Schedule Section
        row_eye = QHBoxLayout()
        self.check_auto = QCheckBox("Auto Schedule")
        self.check_auto.toggled.connect(self.toggle_schedule_ui)
        self.check_auto.stateChanged.connect(self.cb)
        
        self.btn_day = QPushButton("☀ RESET DAY")
        self.btn_day.setObjectName("DayBtn")
        self.btn_day.clicked.connect(self.set_day_mode)
        
        row_eye.addWidget(self.check_auto)
        row_eye.addStretch()
        row_eye.addWidget(self.btn_day)
        self.layout.addLayout(row_eye)
        
        self.sched_frame = QWidget()
        sched_layout = QHBoxLayout(self.sched_frame)
        sched_layout.setContentsMargins(0,0,0,0)
        
        sched_layout.addWidget(QLabel("ON:"))
        self.time_on = QTimeEdit()
        self.time_on.setDisplayFormat("HH:mm")
        self.time_on.setTime(QTime(19, 0)) 
        self.time_on.timeChanged.connect(self.cb)
        sched_layout.addWidget(self.time_on)
        
        sched_layout.addSpacing(10)
        
        sched_layout.addWidget(QLabel("OFF:"))
        self.time_off = QTimeEdit()
        self.time_off.setDisplayFormat("HH:mm")
        self.time_off.setTime(QTime(6, 0))
        self.time_off.timeChanged.connect(self.cb)
        sched_layout.addWidget(self.time_off)
        
        self.layout.addWidget(self.sched_frame)

        # Temperature
        self.sl_temp = NeonSlider("Night Warmth (K)", 1000, 6500, 6500, "#ffaa00", self.cb)
        self.sl_temp.slider.setInvertedAppearance(True) 
        self.layout.addWidget(self.sl_temp)

        self.layout.addSpacing(5)

        # RGB & Vibrance
        self.layout.addWidget(QLabel("RGB & ENHANCEMENTS"))
        self.sl_r = NeonSlider("Red", 10, 100, 100, "#ff4444", self.cb)
        self.layout.addWidget(self.sl_r)
        
        self.sl_g = NeonSlider("Green", 10, 100, 100, "#44ff44", self.cb)
        self.layout.addWidget(self.sl_g)
        
        self.sl_b = NeonSlider("Blue", 10, 100, 100, "#4488ff", self.cb)
        self.layout.addWidget(self.sl_b)

        self.sl_vib = NeonSlider("Digital Vibrance", 0, 100, 0, "#ff00ff", self.cb)
        self.layout.addWidget(self.sl_vib)
        
        self.sl_hue = NeonSlider("Hue Shift", 0, 360, 0, "#aa00ff", self.cb, "°")
        self.layout.addWidget(self.sl_hue)

        main_layout.addWidget(self.frame)
        self.setLayout(main_layout)
        self.resize(320, 650)

    def detect_displays(self):
        self.combo.clear()
        try:
            out = subprocess.check_output("xrandr --query | grep ' connected'", shell=True).decode()
            for line in out.strip().split("\n"):
                if line:
                    monitor = line.split(" ")[0]
                    self.combo.addItem(f"{monitor}")
        except:
            self.combo.addItem("Default Display")

    def toggle_schedule_ui(self):
        self.sched_frame.setVisible(self.check_auto.isChecked())
        self.resize(320, 650 if self.check_auto.isChecked() else 600)

    def set_day_mode(self):
        self.sl_bright.set_value(100)
        self.sl_contrast.set_value(50)
        self.sl_gamma.set_value(100)
        self.sl_temp.set_value(6500)
        self.check_auto.setChecked(False)
        self.sl_r.set_value(100)
        self.sl_g.set_value(100)
        self.sl_b.set_value(100)
        self.sl_vib.set_value(0)
        self.sl_hue.set_value(0)
        self.trigger_update()

    def trigger_update(self):
        if self.parent(): self.parent().schedule_update()

    def show_near_mouse(self):
        c = QCursor.pos()
        self.move(c.x() - 160, c.y() - 400)
        self.show()
        self.activateWindow()

class DisplayEngine(QWidget):
    """Logic Core handling Timers, Settings, and Redshift"""
    def __init__(self):
        super().__init__()
        # Timer for debouncing slider updates (smoothness)
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.apply_settings)

        # Cleanup existing redshift processes
        subprocess.run("killall redshift", shell=True, stderr=subprocess.DEVNULL)
        
        self.ui = NeonPopup(self)
        self.load_settings()
        self.init_tray()
        
        # Auto-Schedule Checker (Runs every 60 seconds)
        self.auto_timer = QTimer()
        self.auto_timer.timeout.connect(self.check_auto_time)
        self.auto_timer.start(60000) 
        
        QTimer.singleShot(2000, self.apply_settings)

    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    d = json.load(f)
                    self.ui.sl_bright.set_value(d.get("b", 100))
                    self.ui.sl_contrast.set_value(d.get("c", 50))
                    self.ui.sl_gamma.set_value(d.get("g", 100))
                    self.ui.sl_temp.set_value(d.get("t", 6500))
                    self.ui.check_auto.setChecked(d.get("auto", False))
                    
                    self.ui.time_on.setTime(QTime(d.get("h_on", 19), d.get("m_on", 0)))
                    self.ui.time_off.setTime(QTime(d.get("h_off", 6), d.get("m_off", 0)))

                    self.ui.sl_r.set_value(d.get("r", 100))
                    self.ui.sl_g.set_value(d.get("g", 100))
                    self.ui.sl_b.set_value(d.get("bb", 100))
                    self.ui.sl_vib.set_value(d.get("v", 0))
                    self.ui.sl_hue.set_value(d.get("h", 0))
            except: pass
        self.ui.toggle_schedule_ui()

    def save_settings(self):
        data = {
            "b": self.ui.sl_bright.slider.value(),
            "c": self.ui.sl_contrast.slider.value(),
            "g": self.ui.sl_gamma.slider.value(),
            "t": self.ui.sl_temp.slider.value(),
            "auto": self.ui.check_auto.isChecked(),
            "h_on": self.ui.time_on.time().hour(),
            "m_on": self.ui.time_on.time().minute(),
            "h_off": self.ui.time_off.time().hour(),
            "m_off": self.ui.time_off.time().minute(),
            "r": self.ui.sl_r.slider.value(),
            "g": self.ui.sl_g.slider.value(),
            "bb": self.ui.sl_b.slider.value(),
            "v": self.ui.sl_vib.slider.value(),
            "h": self.ui.sl_hue.slider.value()
        }
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(data, f)
        except: pass

    def check_auto_time(self):
        if not self.ui.check_auto.isChecked():
            return

        now = datetime.datetime.now().time()
        t_on = self.ui.time_on.time().toPyTime()
        t_off = self.ui.time_off.time().toPyTime()
        
        is_night = False
        if t_on < t_off:
            if t_on <= now <= t_off: is_night = True
        else:
            if now >= t_on or now <= t_off: is_night = True

        current_temp = self.ui.sl_temp.slider.value()
        if is_night:
            if current_temp > 4500: 
                self.ui.sl_temp.set_value(3500) 
                self.schedule_update()
        else:
            if current_temp < 5000:
                self.ui.sl_temp.set_value(6500)
                self.schedule_update()

    def schedule_update(self):
        self.timer.start()

    def apply_settings(self):
        self.save_settings()

        # --- MATH & LOGIC ---
        # Ensure we never pass 0 or negative values to redshift (Causes crash)
        br = max(0.1, self.ui.sl_bright.slider.value() / 100.0)
        temp = self.ui.sl_temp.slider.value()
        
        # Base RGB
        rm = max(0.1, self.ui.sl_r.slider.value() / 100.0)
        gm = max(0.1, self.ui.sl_g.slider.value() / 100.0)
        bm = max(0.1, self.ui.sl_b.slider.value() / 100.0)
        
        # Contrast / Gamma
        con = self.ui.sl_contrast.slider.value()
        gam = max(0.1, self.ui.sl_gamma.slider.value() / 100.0)
        
        contrast_factor = 1.0 + ((50 - con) / 100.0)
        final_gamma = gam * contrast_factor
        
        # Digital Vibrance
        vib = self.ui.sl_vib.slider.value()
        if vib > 0:
            br += (vib / 300.0)
            rm -= (vib / 400.0)
            gm -= (vib / 400.0)
            bm -= (vib / 400.0)
        
        # Safety Check again after math
        rm = max(0.1, rm); gm = max(0.1, gm); bm = max(0.1, bm)
        
        # Hue
        hue = self.ui.sl_hue.slider.value()
        if hue != 0:
            angle = math.radians(hue)
            rm = rm * (1.0 + 0.2 * math.sin(angle))
            gm = gm * (1.0 + 0.2 * math.sin(angle + 2.09))
            bm = bm * (1.0 + 0.2 * math.sin(angle + 4.18))
        
        # Final Gamma Calculation
        g_r = max(0.1, final_gamma / rm)
        g_g = max(0.1, final_gamma / gm)
        g_b = max(0.1, final_gamma / bm)

        if shutil.which("redshift"):
            cmd = f"redshift -P -O {temp} -b {br} -g {g_r}:{g_g}:{g_b}"
            # print(f"Executing: {cmd}") # Uncomment for debugging
            subprocess.run(cmd, shell=True)

    def init_tray(self):
        pix = QPixmap(64,64)
        pix.fill(QColor("transparent"))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Draw Neon Gradient Icon
        grad = QLinearGradient(0,0, 64, 64)
        grad.setColorAt(0, QColor("#00e5ff"))
        grad.setColorAt(1, QColor("#aa00ff"))
        
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        p.drawEllipse(8,8,48,48)
        p.setBrush(QColor("white"))
        p.drawEllipse(28,28,8,8)
        p.end()
        
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(pix))
        self.tray.activated.connect(lambda r: self.ui.show_near_mouse() if r == QSystemTrayIcon.Trigger else None)
        m = QMenu()
        q = QAction("Quit", self)
        q.triggered.connect(QApplication.instance().quit)
        m.addAction(q)
        self.tray.setContextMenu(m)
        self.tray.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # --- SINGLETON LOCK (Prevents Multiple Instances) ---
    socket = QLocalSocket()
    socket.connectToServer(LOCK_NAME)
    if socket.waitForConnected(500):
        # If we can connect, another instance is already running.
        print("Another instance is already running. Exiting.")
        sys.exit(0)
    
    # Start Local Server to hold the lock
    server = QLocalServer()
    server.removeServer(LOCK_NAME)
    server.listen(LOCK_NAME)
    
    # Wait for Tray Availability (System startup handling)
    while not QSystemTrayIcon.isSystemTrayAvailable():
        time.sleep(1)
        
    ex = DisplayEngine()
    sys.exit(app.exec_())
