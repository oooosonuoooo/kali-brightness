#!/usr/bin/env python3
import sys, os, subprocess, json, shutil, time
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QWidget, 
                             QVBoxLayout, QLabel, QSlider, QAction)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QPainter, QPixmap, QColor, QCursor

os.environ["DISPLAY"] = ":0"
CONFIG_FILE = os.path.expanduser("~/.config/kali_brightness_settings.json")

class PopupSlider(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("""
            QWidget { background-color: #1a1a1a; border: 1px solid #444; border-radius: 12px; color: white; }
            QSlider::groove:horizontal { border: 1px solid #333; height: 6px; background: #2a2a2a; margin: 2px 0; border-radius: 3px; }
            QSlider::handle:horizontal { background: #e0e0e0; border: 1px solid #333; width: 16px; margin: -5px 0; border-radius: 8px; }
            QLabel { font-weight: bold; border: none; font-size: 11px; color: #aaaaaa; }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.label_b = QLabel("BRIGHTNESS")
        self.label_b.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label_b)
        self.slider_b = QSlider(Qt.Horizontal)
        self.slider_b.setRange(10, 100)
        self.slider_b.valueChanged.connect(self.on_change)
        layout.addWidget(self.slider_b)

        self.label_t = QLabel("WARMTH")
        self.label_t.setAlignment(Qt.AlignCenter)
        self.label_t.setStyleSheet("color: #ffcc66; margin-top: 8px;") 
        layout.addWidget(self.label_t)
        self.slider_t = QSlider(Qt.Horizontal)
        self.slider_t.setRange(3000, 6500)
        self.slider_t.setInvertedAppearance(True)
        self.slider_t.valueChanged.connect(self.on_change)
        layout.addWidget(self.slider_t)
        self.setLayout(layout)
        self.resize(260, 150)

    def on_change(self):
        if self.parent():
            self.parent().queue_update(self.slider_b.value(), self.slider_t.value())
            self.label_b.setText(f"BRIGHTNESS: {self.slider_b.value()}%")
            self.label_t.setText(f"WARMTH: {self.slider_t.value()}K")

    def show_near_mouse(self):
        c = QCursor.pos()
        self.move(c.x() - 130, c.y() - 160)
        self.show()
        self.activateWindow()

class BrightnessApp(QWidget):
    def __init__(self):
        super().__init__()
        subprocess.run("killall redshift", shell=True, stderr=subprocess.DEVNULL)
        self.bright = 100
        self.temp = 6500
        self.load_config()
        self.debounce = QTimer()
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(100)
        self.debounce.timeout.connect(self.execute)
        self.popup = PopupSlider(self)
        self.popup.slider_b.setValue(self.bright)
        self.popup.slider_t.setValue(self.temp)
        self.initUI()
        QTimer.singleShot(2000, self.execute)
        QTimer.singleShot(5000, self.execute)
        QTimer.singleShot(10000, self.execute)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    d = json.load(f)
                    self.bright = d.get("brightness", 100)
                    self.temp = d.get("temp", 6500)
            except: pass

    def queue_update(self, b, t):
        self.bright = b
        self.temp = t
        self.debounce.start()

    def execute(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"brightness": self.bright, "temp": self.temp}, f)
        except: pass
        if shutil.which("redshift"):
            f_b = max(0.1, self.bright / 100.0)
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            cmd = f"redshift -P -O {self.temp} -b {f_b}"
            try: subprocess.run(cmd, shell=True, timeout=2, env=env)
            except: pass

    def create_icon(self):
        pix = QPixmap(64,64)
        pix.fill(QColor("transparent"))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("white"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(16,16,32,32)
        p.end()
        return QIcon(pix)

    def initUI(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.create_icon())
        self.tray.activated.connect(lambda r: self.popup.show_near_mouse() if r == QSystemTrayIcon.Trigger else None)
        m = QMenu()
        q = QAction("Quit", self)
        q.triggered.connect(QApplication.instance().quit)
        m.addAction(q)
        self.tray.setContextMenu(m)
        self.tray.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    while not QSystemTrayIcon.isSystemTrayAvailable():
        time.sleep(1)
    ex = BrightnessApp()
    sys.exit(app.exec_())
