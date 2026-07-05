# Troubleshooting

## First steps — check session and backend

Run these before anything else:

```bash
echo "Session type : $XDG_SESSION_TYPE"
echo "DISPLAY      : $DISPLAY"
echo "WAYLAND_DISPLAY: $WAYLAND_DISPLAY"
which xrandr
xrandr --query
```

Expected on X11: `XDG_SESSION_TYPE=x11`, `DISPLAY=:0` (or similar), xrandr lists connected outputs.

---

## Wayland session — sliders do nothing

`xrandr` is an **X11-only tool**.  On Wayland it cannot change the display.  Kali Glass shows a warning banner and skips all display commands.

**Fix:** log out and select an X11 session at the login manager (e.g. "Kali Linux (X11)", "GNOME on Xorg", or "Openbox").

---

## VM / VirtualBox — brightness does not change

Virtual display drivers often ignore gamma ramps entirely.

Things to try:

1. Enable 3D acceleration in the VM's display settings.
2. Switch the graphics controller to **VMSVGA** or **VBoxSVGA** in VirtualBox settings.
3. Install VirtualBox Guest Additions inside the VM.
4. Test on a real X11 desktop to confirm the app works outside the VM.

Manual test inside the VM:

```bash
xrandr --output $(xrandr --query | awk '/ connected/{print $1; exit}') --brightness 0.5
```

If nothing changes visually, the driver is ignoring the gamma ramp — this is a VM limitation, not an app bug.

---

## Screen flickers or dims/brightens repeatedly while dragging sliders

This should not happen in v2.1+.  If it does:

1. Check that you are running the latest version:
   ```bash
   python3 kali_glass.py --version  # or head -5 kali_glass.py
   ```
2. Check the log for repeated `xrandr` lines:
   ```bash
   tail -n 50 ~/.config/kali_glass/kali_glass.log
   ```
3. Kill any stale instances and restart:
   ```bash
   pkill -f kali_glass
   python3 kali_glass.py
   ```

---

## Screen stays tinted after exit

Reset all outputs via xrandr:

```bash
for output in $(xrandr --query | awk '/ connected/{print $1}'); do
  xrandr --output "$output" --brightness 1.0 --gamma 1.0:1.0:1.0
done
```

If an external redshift process is running outside Kali Glass, neutralize it too:

```bash
redshift -x
```

The app neutralizes redshift once before manual xrandr control. It keeps the
current display settings when you quit; use the Reset button to return to
neutral brightness/gamma.

---

## Brightness slider does nothing

Verify xrandr works directly:

```bash
# List outputs
xrandr --query

# Dim OUTPUT to 50 %
xrandr --output OUTPUT --brightness 0.5

# Restore
xrandr --output OUTPUT --brightness 1.0
```

Replace `OUTPUT` with your actual output name (e.g. `HDMI-1`, `eDP-1`, `VGA-1`).

If xrandr reports an error, check that `x11-xserver-utils` is installed:

```bash
sudo apt-get install -y x11-xserver-utils
```

---

## Contrast or gamma slider does nothing

The v2.1 backend maps slider values to `xrandr --gamma R:G:B`.  Verify gamma works manually:

```bash
# Slightly warm/contrasty shift
xrandr --output OUTPUT --gamma 1.2:1.2:1.2

# Reset
xrandr --output OUTPUT --gamma 1.0:1.0:1.0
```

If gamma has no effect, your display driver may not support the RANDR gamma ramp.  This is common on some Nvidia setups — try the Nouveau driver or use `nvidia-settings` directly.

---

## RGB sliders have no effect

Same as gamma.  Verify:

```bash
# Reduce blue channel
xrandr --output OUTPUT --gamma 1.0:1.0:0.6

# Reset
xrandr --output OUTPUT --gamma 1.0:1.0:1.0
```

---

## Night mode (warm colour) does nothing

The colour temperature slider now uses pure xrandr gamma offsets — no redshift is needed.  Verify:

```bash
# Simulate warm (3200 K) manually
xrandr --output OUTPUT --gamma 1.0:0.85:0.45

# Reset
xrandr --output OUTPUT --gamma 1.0:1.0:1.0
```

---

## Display list is empty

```bash
xrandr --query
```

If this shows no "connected" outputs, your display session may not be fully initialised.  Try:

- Clicking the refresh button (↺) in the app.
- Waiting a few seconds after login and restarting the app.
- Checking `DISPLAY` is set.

---

## Night warmth resets after reboot

Enable autostart:

```bash
sudo ./install.sh --autostart
```

Check the app is running after login:

```bash
pgrep -af 'kali-glass|kali_glass'
tail -n 50 ~/.config/kali_glass/kali_glass.log
```

---

## PyQt5 is missing

```bash
sudo apt-get update
sudo apt-get install -y python3-pyqt5
python3 -c "from PyQt5.QtWidgets import QApplication; print('PyQt5 OK')"
```

---

## Multiple tray icons / duplicate instances

The app uses a Qt local-server singleton lock.  Kill all instances:

```bash
pkill -f kali_glass.py
pkill -f /usr/local/bin/kali-glass
```

Then start once:

```bash
kali-glass
```

---

## Run backend diagnostics

Right-click the tray icon → **🔍 Test Backend**.  A dialog shows:

- Session type
- DISPLAY value
- xrandr path
- redshift path
- detected outputs
- chosen backend
- last command run

The full log is at:

```bash
tail -n 100 ~/.config/kali_glass/kali_glass.log
```

---

## Installer dry run

Preview installer actions without changing the system:

```bash
./install.sh --dry-run
```

Enable or disable autostart explicitly:

```bash
sudo ./install.sh --autostart
sudo ./install.sh --disable-autostart
```

Uninstall:

```bash
sudo ./install.sh --uninstall
```

---

## Known limitations

| Limitation | Detail |
| --- | --- |
| Wayland | Global gamma and brightness control is intentionally restricted by Wayland. Use X11. |
| VMs | Virtual drivers may ignore display gamma ramps. |
| HDR | xrandr does not provide proper HDR colour management. |
| Some Nvidia setups | `xrandr --gamma` may not affect output on proprietary drivers. |
| Missing tray | App continues after tray timeout, but panel access depends on the desktop environment. |
