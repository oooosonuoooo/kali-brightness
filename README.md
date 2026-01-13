# 💎 v1.1: The "Master Glass" Update

> **A major overhaul featuring a transparent "Neon Glass" theme, professional color grading, and bulletproof stability.**

We have completely redesigned the UI to look modern and fluid on Kali Linux, while adding powerful tools like RGB Gamma control and Digital Vibrance.

## 📸 Screenshots
<p align="center">
  <img width="48%" alt="Main Interface" src="https://github.com/user-attachments/assets/80d1439a-c21f-4b62-923c-4b4e28db3877" />
  <img width="48%" alt="Settings & Schedule" src="https://github.com/user-attachments/assets/313c4b1b-d28a-44b4-8a41-4df273135d97" />
</p>

---

## ✨ New Features
* **🔮 Neon Glass UI:** A brand new semi-transparent interface with drop shadows and smooth neon gradients.
* **🎨 Full RGB Control:** You can now adjust Red, Green, and Blue gamma channels independently for color correction.
* **🌈 Digital Vibrance:** Added a dedicated slider to boost color saturation and clarity.
* **🔄 Hue Shift:** New control to rotate color hue for advanced customization.
* **⏰ Auto-Schedule:** Set custom Start/End times for automatic Eye Protection mode.

## 🛡️ Stability & Fixes
* **🔒 Singleton Lock:** Fixed the issue where multiple app instances would open on restart. Now guarantees only **one** instance runs at a time.
* **🧮 Math Safety:** Added safeguards to prevent crashes when sliders are dragged rapidly or to invalid values.
* **🚀 Smart Installer:** The new `install.sh` automatically installs dependencies (`redshift`, `pyqt5`), sets permissions, and configures **Auto-Start** on boot.

---

## 📦 How to Install / Update
Run the following commands in your terminal to install the update:

```bash
git clone https://github.com/oooosonuoooo/kali-brightness.git
cd kali-brightness
chmod +x install.sh
sudo ./install.sh
