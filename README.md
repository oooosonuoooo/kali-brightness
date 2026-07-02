# Kali Glass Controller

Kali Glass Controller is a PyQt5 tray app for X11 display tuning on Kali Linux and other desktop Linux distributions. It controls brightness, gamma, RGB balance, color temperature, night mode, and simple scheduled day/night switching through `redshift` and `xrandr`.

## Features

| Feature | Notes |
| --- | --- |
| Brightness | Software brightness from 1% to 100% using `xrandr` when available. |
| Color temperature | Uses `redshift` one-shot mode for warm/cool display output. |
| RGB gamma | Separate red, green, and blue channel multipliers. |
| Contrast/gamma | Gamma-based contrast and multiplier controls. |
| Digital vibrance | Saturation-style boost without raising brightness. |
| Hue shift | Small RGB rotation effect for tint adjustment. |
| Auto schedule | Applies day/night presets at configured times. |
| Multi-monitor | Detects X11 outputs through `xrandr`; can target all displays or one output. |
| Tray app | Floating panel with tray menu and single-instance lock. |
| Safe fallback | Missing tools are reported in the UI/log instead of crashing the app. |

## Requirements

| Package | Purpose |
| --- | --- |
| `python3` | Runtime. |
| `python3-pyqt5` | GUI framework. |
| `redshift` | Primary brightness/color-temperature backend. |
| `x11-xserver-utils` | Provides `xrandr` for display detection and fallback gamma control. |

Full functionality requires an X11 desktop session. Wayland sessions usually block `redshift` and `xrandr` display changes.

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

The tray icon toggles the panel with left click and opens a menu with right click. Settings are saved automatically in:

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

## Development Checks

```bash
python3 -m py_compile kali_glass.py
bash -n install.sh
ruff check .
pylint kali_glass.py
```

`shellcheck install.sh` is useful when ShellCheck is installed.

## Known Limitations

| Environment | Behavior |
| --- | --- |
| X11 | Supported path with `redshift`/`xrandr`. |
| Wayland | App can start, but display commands may fail because Wayland restricts global gamma/brightness tools. |
| VM/VirtualBox | Gamma and brightness may be ignored by the virtual display driver. |
| SSH/headless | The app exits cleanly when no graphical display session is available. |
| Nvidia proprietary driver | `xrandr --gamma` may be ineffective; `redshift` may work better. |
| Missing `redshift` | Falls back to `xrandr` brightness/gamma where possible. |
| Missing `xrandr` | Display list and fallback control are unavailable; the app reports the missing tool. |

## Project Layout

```text
kali_glass.py       Main PyQt5 tray application.
install.sh          Installer, autostart manager, and uninstaller.
TROUBLESHOOTING.md  Recovery steps and environment notes.
```

## Safety Notes

The app avoids `sudo` at runtime. Root is only needed for the installer because it writes `/usr/local/bin/kali-glass` and `/usr/share/applications/kali-glass.desktop`.

The Python command runner executes argument lists without `shell=True`, reports non-zero exits correctly, and uses timeouts for synchronous utility calls. The app does not force `DISPLAY=:0`; start it from the active graphical session or set `DISPLAY` yourself when appropriate.

## License

MIT
