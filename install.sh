#!/bin/bash
# KALI GLASS - ULTIMATE INSTALLER
# This script installs dependencies, the app, and sets up auto-start.

echo -e "\e[1;36m[*] KALI GLASS INSTALLER INITIALIZED...\e[0m"

# 1. Check for Root (We need permission to install system packages)
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo ./install.sh)"
  exit
fi

# 2. Install Dependencies (The "Engine")
echo -e "\e[1;33m[*] Installing Redshift Engine & Python Libraries...\e[0m"
apt-get update -qq
apt-get install -y redshift python3-pyqt5 python3-pip x11-xserver-utils

# 3. Move App to System Binaries
echo -e "\e[1;33m[*] Installing Application to /usr/local/bin/...\e[0m"
cp kali_glass.py /usr/local/bin/kali-glass
chmod +x /usr/local/bin/kali-glass

# 4. Create Desktop Entry (For Menu)
echo -e "\e[1;33m[*] Creating Menu Shortcut...\e[0m"
cat << EODESKTOP > /usr/share/applications/kali-glass.desktop
[Desktop Entry]
Name=Kali Glass Controller
Comment=Ultimate Display Control Center
Exec=/usr/local/bin/kali-glass
Icon=display
Terminal=false
Type=Application
Categories=Utility;Settings;
EODESKTOP

# 5. Setup Auto-Start (For the actual user, not root)
# We detect the real user who ran the sudo command
REAL_USER=${SUDO_USER:-$USER}
USER_HOME=$(getent passwd $REAL_USER | cut -d: -f6)
AUTOSTART_DIR="$USER_HOME/.config/autostart"

echo -e "\e[1;33m[*] Setting up Auto-Start for user: $REAL_USER...\e[0m"
mkdir -p "$AUTOSTART_DIR"
cat << EOAUTO > "$AUTOSTART_DIR/kali-glass.desktop"
[Desktop Entry]
Type=Application
Exec=/usr/local/bin/kali-glass
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name[en_US]=Kali Glass
Name=Kali Glass
Comment=Start Kali Glass on Boot
EOAUTO

chown -R $REAL_USER:$REAL_USER "$AUTOSTART_DIR"

echo -e "\e[1;32m[+] INSTALLATION COMPLETE!\e[0m"
echo "You can now launch 'Kali Glass Controller' from your menu,"
echo "or it will start automatically next time you login."
echo ""
echo "Launching it for you now..."
sudo -u $REAL_USER nohup python3 /usr/local/bin/kali-glass >/dev/null 2>&1 &
