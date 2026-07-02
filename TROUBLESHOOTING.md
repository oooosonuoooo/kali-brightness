# Troubleshooting

## Screen Stays Tinted After Exit

Reset `redshift`:

```bash
redshift -x
```

Reset each connected X11 output:

```bash
for output in $(xrandr --query | awk '/ connected/{print $1}'); do
  xrandr --output "$output" --brightness 1.0 --gamma 1.0:1.0:1.0
done
```

## Night Warmth Resets After Reboot

Install the current version and enable autostart explicitly:

```bash
sudo ./install.sh --autostart
```

The app reapplies saved settings several times during startup so it can recover when the desktop, tray, or RANDR backend is slow to become available after login. If warmth still resets, confirm the app is running after login and check the log:

```bash
pgrep -af 'kali-glass|kali_glass'
tail -n 100 ~/.config/kali_glass/kali_glass.log
```

## PyQt5 Is Missing

```bash
sudo apt-get update
sudo apt-get install -y python3-pyqt5
```

Then verify:

```bash
python3 -c "from PyQt5.QtWidgets import QApplication; print('ok')"
```

## No Graphical Display Session

The app must be started from a graphical desktop session. Check:

```bash
echo "$DISPLAY"
echo "$XDG_SESSION_TYPE"
```

For local X11 desktops, `DISPLAY` is commonly `:0` or similar. For SSH, use proper X forwarding (`ssh -X`) or start the app locally from the desktop session.

## Wayland Session

`redshift` and `xrandr` are X11 tools. On Wayland the panel may open, but display changes may fail. Log out and choose an X11 session if your desktop login manager provides one.

## Multiple Tray Icons Or Duplicate Instances

The app uses a Qt local-server singleton lock. If an old process is still alive:

```bash
pkill -f kali_glass.py
pkill -f /usr/local/bin/kali-glass
```

Then start it again:

```bash
kali-glass
```

## Brightness Slider Does Nothing In A VM

Virtual display drivers often ignore gamma and software brightness changes. Try:

- Enabling 3D acceleration in the VM settings.
- Switching VirtualBox graphics controller to VMSVGA or VBoxSVGA.
- Testing on a real X11 desktop session.

## Display List Is Empty

Check that `xrandr` can see outputs:

```bash
xrandr --query
```

If this fails, install the X11 utilities package:

```bash
sudo apt-get install -y x11-xserver-utils
```

## redshift Errors

Kali Glass uses manual one-shot mode, so location is not required. If a user redshift config causes trouble, temporarily move it aside:

```bash
mv ~/.config/redshift.conf ~/.config/redshift.conf.bak
```

## Installer Dry Run

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

## Logs

```bash
tail -n 100 ~/.config/kali_glass/kali_glass.log
```

## Remaining Limitations

| Limitation | Detail |
| --- | --- |
| Wayland | Global gamma and brightness control is intentionally restricted. |
| VMs | Virtual drivers may ignore display gamma ramps. |
| HDR | `redshift` does not provide proper HDR color management. |
| Some Nvidia setups | `xrandr --gamma` may not affect output. |
| Missing tray | The app continues after a tray timeout, but panel access depends on the desktop environment. |
