#!/usr/bin/env bash
# Kali Glass Controller installer
# Supports Kali Linux, Debian, Ubuntu, Fedora, Arch, and derivatives.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { printf "%b[*]%b %s\n" "$CYAN" "$NC" "$*"; }
ok()    { printf "%b[+]%b %s\n" "$GREEN" "$NC" "$*"; }
warn()  { printf "%b[!]%b %s\n" "$YELLOW" "$NC" "$*"; }
error() { printf "%b[x]%b %s\n" "$RED" "$NC" "$*" >&2; }
die()   { error "$*"; exit 1; }

APP_NAME="kali-glass"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="$SCRIPT_DIR/kali_glass.py"
INSTALL_PATH="/usr/local/bin/$APP_NAME"
DESKTOP_PATH="/usr/share/applications/$APP_NAME.desktop"

INSTALL_DEPS=1
DRY_RUN=0
LAUNCH=0
UNINSTALL=0
PURGE_CONFIG=0
AUTOSTART_MODE="unchanged"
TARGET_USER="${SUDO_USER:-${USER:-}}"

usage() {
    cat <<EOF
Kali Glass Controller installer

Usage:
  sudo ./install.sh [options]

Options:
  --dry-run            Show planned actions without changing the system.
  --no-deps            Do not install OS packages.
  --autostart          Enable login autostart for the target user.
  --disable-autostart  Remove the target user's autostart entry.
  --user USER          Target user for autostart/launch/config cleanup.
  --launch             Launch the app after installation when DISPLAY is set.
  --uninstall          Remove installed files and autostart entry.
  --purge-config       With --uninstall, remove ~/.config/kali_glass too.
  -h, --help           Show this help.

Autostart is unchanged unless --autostart or --disable-autostart is provided.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --no-deps) INSTALL_DEPS=0 ;;
        --autostart) AUTOSTART_MODE="enable" ;;
        --disable-autostart|--no-autostart) AUTOSTART_MODE="disable" ;;
        --user)
            [ "${2:-}" ] || die "--user requires a username"
            TARGET_USER="$2"
            shift
            ;;
        --launch) LAUNCH=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --purge-config) PURGE_CONFIG=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
    shift
done

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf "DRY-RUN:"
        printf " %q" "$@"
        printf "\n"
    else
        "$@"
    fi
}

require_root() {
    if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
        die "Root is required to write /usr/local/bin and /usr/share/applications. Use: sudo ./install.sh"
    fi
}

require_source() {
    [ -f "$SOURCE_FILE" ] || die "kali_glass.py not found at: $SOURCE_FILE"
}

resolve_target_user() {
    if [ -z "$TARGET_USER" ]; then
        TARGET_USER="root"
    fi
    if ! getent passwd "$TARGET_USER" >/dev/null; then
        die "Target user does not exist: $TARGET_USER"
    fi
    USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
    TARGET_GROUP="$(id -gn "$TARGET_USER")"
    AUTOSTART_DIR="$USER_HOME/.config/autostart"
    AUTOSTART_PATH="$AUTOSTART_DIR/$APP_NAME.desktop"
}

detect_pkg_manager() {
    if command -v apt-get >/dev/null 2>&1; then
        PKG_MANAGER="apt-get"
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MANAGER="dnf"
    elif command -v pacman >/dev/null 2>&1; then
        PKG_MANAGER="pacman"
    else
        PKG_MANAGER=""
    fi
}

install_dependencies() {
    if [ "$INSTALL_DEPS" -eq 0 ]; then
        warn "Skipping dependency installation (--no-deps)."
        return
    fi

    detect_pkg_manager
    case "$PKG_MANAGER" in
        apt-get)
            info "Installing dependencies with apt-get..."
            run apt-get update -qq
            run env DEBIAN_FRONTEND=noninteractive apt-get install -y \
                python3 python3-pyqt5 redshift x11-xserver-utils
            ;;
        dnf)
            info "Installing dependencies with dnf..."
            run dnf install -y python3 python3-qt5 redshift xrandr
            ;;
        pacman)
            info "Installing dependencies with pacman..."
            run pacman -Sy --noconfirm python python-pyqt5 redshift xorg-xrandr
            ;;
        *)
            warn "No supported package manager found. Install python3, PyQt5, redshift, and xrandr manually."
            ;;
    esac
}

install_app() {
    info "Installing $APP_NAME to $INSTALL_PATH..."
    run install -D -m 0755 "$SOURCE_FILE" "$INSTALL_PATH"
    ok "Application installed."
}

write_desktop_entry() {
    info "Writing desktop launcher..."
    if [ "$DRY_RUN" -eq 1 ]; then
        printf "DRY-RUN: write %s\n" "$DESKTOP_PATH"
        return
    fi

    install -d -m 0755 "$(dirname "$DESKTOP_PATH")"
    cat > "$DESKTOP_PATH" <<EOF
[Desktop Entry]
Version=1.0
Name=Kali Glass Controller
GenericName=Display Controller
Comment=Display brightness, gamma, and night-mode controller for X11
Exec=$INSTALL_PATH
Icon=preferences-desktop-display
Terminal=false
Type=Application
Categories=Utility;Settings;HardwareSettings;
Keywords=brightness;gamma;night;display;monitor;redshift;xrandr;
StartupNotify=false
EOF
    chmod 644 "$DESKTOP_PATH"
    ok "Desktop launcher: $DESKTOP_PATH"
}

write_autostart_entry() {
    info "Enabling autostart for user: $TARGET_USER"
    if [ "$DRY_RUN" -eq 1 ]; then
        printf "DRY-RUN: write %s\n" "$AUTOSTART_PATH"
        return
    fi

    install -d -m 0755 "$AUTOSTART_DIR"
    cat > "$AUTOSTART_PATH" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Kali Glass Controller
Comment=Start Kali Glass Controller on login
Exec=$INSTALL_PATH
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
StartupNotify=false
EOF
    chown "$TARGET_USER:$TARGET_GROUP" "$AUTOSTART_DIR" "$AUTOSTART_PATH"
    chmod 644 "$AUTOSTART_PATH"
    ok "Autostart enabled: $AUTOSTART_PATH"
}

disable_autostart_entry() {
    info "Disabling autostart for user: $TARGET_USER"
    run rm -f "$AUTOSTART_PATH"
    ok "Autostart entry removed if it existed."
}

verify_installation() {
    if [ "$DRY_RUN" -eq 1 ]; then
        info "Dry-run mode: skipping live installation verification."
        return
    fi

    info "Verifying installation..."
    local fail=0
    [ -x "$INSTALL_PATH" ] && ok "Binary: $INSTALL_PATH" || { error "Binary missing or not executable"; fail=1; }
    [ -f "$DESKTOP_PATH" ] && ok "Desktop entry: $DESKTOP_PATH" || { error "Desktop entry missing"; fail=1; }
    command -v python3 >/dev/null 2>&1 && ok "python3: $(python3 --version)" || { error "python3 not found"; fail=1; }
    python3 -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null && ok "PyQt5 import: OK" || { error "PyQt5 import failed"; fail=1; }
    command -v redshift >/dev/null 2>&1 && ok "redshift: $(redshift -V 2>&1 | head -1)" || warn "redshift not found; color temperature control will be unavailable."
    command -v xrandr >/dev/null 2>&1 && ok "xrandr: $(xrandr --version 2>&1 | head -1)" || warn "xrandr not found; display detection/fallback control will be unavailable."

    [ "$fail" -eq 0 ] || die "Installation verification failed."
}

launch_app() {
    if [ "$LAUNCH" -ne 1 ]; then
        return 0
    fi
    if [ -z "${DISPLAY:-}" ]; then
        warn "DISPLAY is not set; skipping launch."
        return
    fi
    info "Launching as user: $TARGET_USER"
    if [ "$DRY_RUN" -eq 1 ]; then
        printf "DRY-RUN: launch %s for %s on DISPLAY=%s\n" "$INSTALL_PATH" "$TARGET_USER" "$DISPLAY"
        return
    fi
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$TARGET_USER" -- sh -c "DISPLAY='${DISPLAY}' XAUTHORITY='${XAUTHORITY:-}' nohup '$INSTALL_PATH' >/dev/null 2>&1 &"
    else
        sudo -u "$TARGET_USER" sh -c "DISPLAY='${DISPLAY}' XAUTHORITY='${XAUTHORITY:-}' nohup '$INSTALL_PATH' >/dev/null 2>&1 &"
    fi
    ok "Launch requested."
}

uninstall_app() {
    info "Removing installed files..."
    run rm -f "$INSTALL_PATH" "$DESKTOP_PATH"
    run rm -f "$AUTOSTART_PATH"
    if [ "$PURGE_CONFIG" -eq 1 ]; then
        run rm -rf "$USER_HOME/.config/kali_glass"
    fi
    ok "Uninstall complete."
}

printf "\n%bKALI GLASS CONTROLLER - Installer v2.0%b\n\n" "$BOLD$CYAN" "$NC"

require_root
resolve_target_user

if [ "$UNINSTALL" -eq 1 ]; then
    uninstall_app
    exit 0
fi

require_source
install_dependencies
install_app
write_desktop_entry

case "$AUTOSTART_MODE" in
    enable) write_autostart_entry ;;
    disable) disable_autostart_entry ;;
    unchanged) info "Autostart unchanged. Use --autostart to enable or --disable-autostart to remove it." ;;
esac

verify_installation
launch_app

printf "\n%bInstallation complete.%b\n" "$GREEN$BOLD" "$NC"
printf "Run: %s\n" "$APP_NAME"
printf "Autostart: %s\n" "$AUTOSTART_MODE"
printf "Session note: X11 gives full support; Wayland support is limited by redshift/xrandr.\n"
