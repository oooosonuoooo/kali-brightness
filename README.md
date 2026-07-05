# Kali Glass Controller

Kali Glass Controller is a PyQt5 tray app for X11 display tuning on Kali Linux and other desktop Linux distributions.  It controls brightness, gamma, RGB balance, colour temperature, night mode, and scheduled day/night switching entirely through `xrandr`.

> **Full control requires an X11 session.**  Wayland restricts global gamma and brightness tools — the app will display a clear warning and skip display commands on Wayland.

## Features

| Feature | Notes |
| --- | --- |
| Brightness | Software brightness 5–100 % mapped directly to `xrandr --brightness` (5 % → 0.05, 50 % → 0.5, 100 % → 1.0). |
| Contrast | Contrast slider 50 = neutral (no change), > 50 = higher contrast, < 50 = lower contrast. |
| Gamma | Gamma slider 100 = neutral (1.0), 50 = 0.5, 200 = 2.0. Applied per channel via `xrandr --gamma`. |
| RGB channels | Separate red, green, and blue gamma multipliers, clamped to safe xrandr values. |
| Colour temperature | Warm/cool shift (1 000 K – 6 500 K) implemented as RGB gamma offsets — no redshift dependency. |
| Night mode | One-click warm preset (3 200 K, 70 % brightness). |
| Auto schedule | Applies day/night presets at user-configured times. |
| Multi-monitor | Detects X11 outputs through `xrandr --query`; targets all displays or a single output. |
| Anti-flicker | 300 ms debounce + "latest wins" logic: never kills a running command; applies only the newest pending settings after the current command completes. |
| Diagnostics | Startup log and "Test Backend" tray action shows session type, DISPLAY, xrandr path, detected outputs, last command, and errors. |
| Tray app | Floating panel with tray menu and single-instance lock. |
| Safe fallback | Missing tools are reported in the UI and log instead of crashing. |

## Requirements

| Package | Purpose |
| --- | --- |
| `python3` | Runtime. |
| `python3-pyqt5` | GUI framework. |
| `x11-xserver-utils` | Provides `xrandr` for all display control. |
| `brightnessctl` | Optional fallback when a real `/sys/class/backlight` device exists. Normal X11 control does not require it. |

### Why X11 is required

`xrandr` is an X11-only protocol tool.  On Wayland it cannot connect to the display and will fail silently or with an error.  The Kali Glass UI will still open under Wayland, but all display-control sliders will be disabled and a warning banner is shown.

**Fix:** log out of your Wayland session and select "Kali Linux (X11)" or "GNOME on Xorg" at the login screen.

## Install

Preview the installation first:

```bash
./install.sh --dry-run
```

Install system-wide:

```bash
sudo ./install.sh
```

Install and enable login autostart for your user:

```bash
sudo ./install.sh --autostart
```

Install without changing packages:

```bash
sudo ./install.sh --no-deps
```

Install and launch immediately when `DISPLAY` is set:

```bash
sudo ./install.sh --launch
```

Autostart is not changed unless `--autostart` or `--disable-autostart` is supplied.

## Usage

After installation:

```bash
kali-glass
```

From source:

```bash
python3 kali_glass.py
```

The tray icon toggles the panel with left click and opens a menu with right click.  Settings are saved automatically in:

```text
~/.config/kali_glass/config.json
```

Logs are written to:

```text
~/.config/kali_glass/kali_glass.log
```

For temporary runs, override the paths without touching your live profile:

```bash
KALI_GLASS_CONFIG=/tmp/kali-glass-config.json \
KALI_GLASS_LOG=/tmp/kali-glass.log \
python3 kali_glass.py
```

## Manual test commands

Use these to verify the X11 backend independently:

```bash
# List connected outputs
xrandr --query

# Dim a specific output to 70 %
xrandr --output HDMI-1 --brightness 0.7

# Apply a warm colour shift
xrandr --output HDMI-1 --gamma 1.0:0.85:0.45

# Reset a specific output to neutral
xrandr --output HDMI-1 --brightness 1.0 --gamma 1.0:1.0:1.0

# Reset all outputs to neutral (shell loop)
for output in $(xrandr --query | awk '/ connected/{print $1}'); do
  xrandr --output "$output" --brightness 1.0 --gamma 1.0:1.0:1.0
done
```

## Uninstall

Remove the installed app, desktop entry, and autostart entry:

```bash
sudo ./install.sh --uninstall
```

Also remove saved user config:

```bash
sudo ./install.sh --uninstall --purge-config
```

Remove only the autostart entry:

```bash
sudo ./install.sh --disable-autostart
```

## Development checks

```bash
python3 -m py_compile kali_glass.py && echo "Syntax OK"
bash -n install.sh && echo "Shell syntax OK"
```

Optional linting:

```bash
ruff check .
pylint kali_glass.py
```

## Known limitations

| Environment | Behaviour |
| --- | --- |
| **X11** | Full support via `xrandr`. |
| **Wayland** | App opens with a warning banner; display changes are skipped. Log out and choose an X11 session. |
| **VM / VirtualBox** | Virtual display drivers often ignore gamma ramps.  Enable 3D acceleration or switch to VMSVGA/VBoxSVGA in VM settings. |
| **SSH / headless** | App exits cleanly when no graphical session is detected. |
| **Nvidia proprietary** | `xrandr --gamma` may be ineffective on some Nvidia setups; try switching to the Nouveau driver or use `nvidia-settings`. |
| **Missing xrandr** | All display control is unavailable; the UI shows an error. |

## Project layout

```text
kali_glass.py       Main PyQt5 tray application (xrandr backend, anti-flicker).
install.sh          Installer, autostart manager, and uninstaller.
README.md           This file.
TROUBLESHOOTING.md  Recovery steps and environment notes.
```

## Safety notes

The app avoids `sudo` at runtime.  Root is only needed for the installer because it writes `/usr/local/bin/kali-glass` and `/usr/share/applications/kali-glass.desktop`.

The Python command runner executes argument lists without `shell=True`, reports non-zero exits to the log, and uses timeouts for synchronous utility calls.  The app does not force `DISPLAY=:0`; start it from the active graphical session or set `DISPLAY` yourself when appropriate.

## Changelog

### v2.1 (current)
- **xrandr-only backend** — removed redshift/xrandr conflicts that caused flickering.
- **Anti-flicker**: 300 ms debounce + "latest wins" — never kills a running process mid-command.
- **Brightness fix**: 100 % = xrandr 1.0, 50 % = 0.5, 5 % = 0.05.
- **Contrast fix**: neutral value 50 produces no change; moving above/below 50 visibly shifts contrast.
- **Colour temperature** via pure xrandr gamma offsets (no redshift dependency for temp control).
- **Wayland**: clear warning banner + silent skip of display commands.
- **Diagnostics**: startup log + "Test Backend" tray menu action.
- **Display targeting**: proper "All Displays" vs single-output logic.
- **Quit**: keeps the current display settings; use **Reset** to restore xrandr 1.0/neutral.

### v2.0
- Initial public release.

## License

MIT
