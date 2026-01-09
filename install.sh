#!/bin/bash
set -e
echo "[+] Installing Dependencies..."
sudo apt-get update -qq
sudo apt-get install -y redshift python3-pyqt5 coreutils

echo "[+] Removing Conflicts..."
killall redshift 2>/dev/null || true
systemctl --user stop redshift 2>/dev/null || true
systemctl --user mask redshift 2>/dev/null || true
rm -f ~/.config/redshift.conf

echo "[+] Installing App..."
sudo cp kali_brightness.py /usr/local/bin/kali-brightness.py
sudo chmod +x /usr/local/bin/kali-brightness.py

echo "[+] Creating Auto-Start Entry..."
mkdir -p ~/.config/autostart
cat << EODESK > ~/.config/autostart/kali-brightness.desktop
[Desktop Entry]
Type=Application
Exec=sh -c 'sleep 10 && python3 /usr/local/bin/kali-brightness.py'
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Kali Brightness
Icon=display-brightness-symbolic
EODESK

echo "[+] Launching now..."
nohup python3 /usr/local/bin/kali-brightness.py >/dev/null 2>&1 &
echo "SUCCESS! The White Circle icon should appear in your tray."
