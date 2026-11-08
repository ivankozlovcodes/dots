# xrdp + XFCE remote desktop (minerva)

## What it does

- Separate virtual XFCE desktop over RDP for the Pixel 11 Pro Fold via Tailscale. The local kiosk (tty1 getty autologin -> ~/.bash_profile/.profile startx -> ~/.xinitrc -> chromium --kiosk on :0) is untouched.
- xrdp sessions run as the same user `minerva` on display :10+.
- xrdp 0.10.1 + xorgxrdp 0.10.2 (Debian 13).
- Listens ONLY on Tailscale IPs `100.66.141.66:3389` and `[fd7a:115c:a1e0::5301:8dc8]:3389`. No firewall rule is needed: the INPUT policy is ACCEPT, so the bind address is the control.
- MagicDNS name: `minerva.tail9e3eb4.ts.net`.
- If the node's Tailscale IP ever changes, update `port=` in `xrdp.ini` and the systemd drop-in.
- Session: `/etc/xrdp/startwm.sh` runs `dbus-run-session -- startxfce4`. It uses a private D-Bus, does not source ~/.profile or Xsession, and refuses DISPLAY :0.
- Disconnect keeps the session; reconnect rejoins it (`KillDisconnected=false`, `Policy=Default`).
- Dynamic resize: `enable_dynamic_resizing=true`. xorgxrdp RandR accepts up to 16384x16384 (tested at 2076x2152).
- Phone fit (remote session only, config in ~/.config/xfce4, read only by XFCE):
  - Xft/DPI 192.
  - One bottom panel, 112 px; icons 64 px (app menu, window list, logout/actions).
  - xfwm4 theme Default-xhdpi (58 px title bars), no compositor, wireframe move/resize.
  - Solid dark background, no desktop icons.
  - No session save, no lock/screensaver (`xset s off -dpms` in startwm.sh).
  - Autostart overrides hide localsearch-3, geoclue-demo-agent, and print-applet in XFCE.
- A polkit rule suppresses colord and PackageKit refresh popups.

## Files

| Repo path (under `den/minerva/`) | Host path | Mode |
|---|---|---|
| `etc/xrdp/xrdp.ini` | `/etc/xrdp/xrdp.ini` | 644 |
| `etc/xrdp/sesman.ini` | `/etc/xrdp/sesman.ini` | 644 |
| `etc/xrdp/startwm.sh` | `/etc/xrdp/startwm.sh` | 755 |
| `etc/systemd/system/xrdp.service.d/10-tailscale.conf` | same path under `/` | 644 |
| `etc/polkit-1/rules.d/45-xrdp-no-popups.rules` | same path under `/` | 644 |
| `HOME/.config/xfce4/xfconf/xfce-perchannel-xml/{xsettings,xfwm4,xfce4-panel,xfce4-desktop,xfce4-session}.xml` | `~/.config/xfce4/xfconf/xfce-perchannel-xml/` | 644 |
| `HOME/.config/autostart/{localsearch-3,geoclue-demo-agent,print-applet}.desktop` | `~/.config/autostart/` | 644 |
| `HOME/.local/bin/xrdp-test-connect` | `~/.local/bin/` (test script) | 755 |

The systemd drop-in waits for Tailscale IPs and sets `Restart=on-failure`.

Never commit `/etc/xrdp/*.pem`, `rsakeys.ini`, or Tailscale state.

## Apply on a fresh machine

Run as `minerva` with sudo:

```bash
set -e
D=~/git/dots/den/minerva
# config first, so xrdp never starts listening on all interfaces
sudo install -d -m 755 /etc/xrdp
sudo install -m 644 $D/etc/xrdp/xrdp.ini $D/etc/xrdp/sesman.ini /etc/xrdp/
sudo install -m 755 $D/etc/xrdp/startwm.sh /etc/xrdp/startwm.sh
sudo install -D -m 644 $D/etc/systemd/system/xrdp.service.d/10-tailscale.conf /etc/systemd/system/xrdp.service.d/10-tailscale.conf
sudo install -m 644 $D/etc/polkit-1/rules.d/45-xrdp-no-popups.rules /etc/polkit-1/rules.d/
sudo systemctl daemon-reload
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
  xrdp xorgxrdp dbus-x11 xfce4-session xfwm4 xfce4-panel xfdesktop4 xfce4-settings xfce4-terminal thunar
# optional test tools: freerdp3-x11 xvfb x11-apps
sudo adduser xrdp ssl-cert
sudo systemctl enable xrdp xrdp-sesman
sudo systemctl restart xrdp
# user files (no sudo)
install -D -m 644 -t ~/.config/xfce4/xfconf/xfce-perchannel-xml $D/HOME/.config/xfce4/xfconf/xfce-perchannel-xml/*.xml
install -D -m 644 -t ~/.config/autostart $D/HOME/.config/autostart/*.desktop
install -D -m 755 $D/HOME/.local/bin/xrdp-test-connect ~/.local/bin/xrdp-test-connect
```

Before the real install, do a dry run and confirm no display manager (lightdm, gdm3, sddm, nodm) or screen locker gets pulled in:

```bash
apt-get install -s --no-install-recommends xrdp xorgxrdp dbus-x11 xfce4-session xfwm4 xfce4-panel xfdesktop4 xfce4-settings xfce4-terminal thunar
```

Verify the bind addresses with:

```bash
sudo ss -tlnp | grep 3389
```

Only the two Tailscale addresses should appear.

Alternatively, `den/conf-sync` can push the files.

## Phone: Pixel 11 Pro Fold (aFreeRDP / aRDP from F-Droid)

- Host: `minerva.tail9e3eb4.ts.net` (or `100.66.141.66`), port 3389, user `minerva`, your login password. The Tailscale app must be connected.
- Accept the self-signed certificate on first connect.
- aFreeRDP:
  - Screen settings -> Resolution "Automatic" (uses the current screen: 2076x2152 unfolded, 1080x2342 folded).
  - Colors "High Color (16 bit)" on mobile data, or "True Color (32 bit)" on Wi-Fi.
  - Performance: disable wallpaper, theming, desktop composition, full-window drag, and menu animations; enable RemoteFX/GFX.
  - Advanced -> Security: TLS.
  - Input: touch-pointer mode (the on-screen mouse pointer) for precise clicks on window controls; use the keyboard button for text.
- Dynamic resize on fold, unfold, or rotate needs the client's display-control (MS-RDPEDISP) support.
  - aFreeRDP: leave resolution on Automatic. If a resize does not follow, disconnect and reconnect; the session is kept and rejoined at the new size.
  - aRDP: set "Resolution: Fit to screen / automatic" and enable "Resize remote desktop to fit" or "dynamic resolution" if offered. Otherwise reconnect after folding.
- Log out via the panel's logout (actions) button to end the session. Just closing the app leaves it running.

## Adjusting scaling later

Inside the remote session:

- DPI: Settings -> Appearance -> Fonts -> DPI, or `xfconf-query -c xsettings -p /Xft/DPI -s 168`.
- Panel size: right-click the panel -> Panel -> Panel Preferences (row size / icon size), or `xfconf-query -c xfce4-panel -p /panels/panel-1/size -s 96`.
- Title bars: Settings -> Window Manager -> Style (Default-hdpi = 43 px, Default = 29 px).

Copy any changed XML from `~/.config/xfce4/xfconf/xfce-perchannel-xml` back into this repo.

## Test from the machine itself

Run `xrdp-test-connect`. It runs xfreerdp3 at 2076x2152 inside Xvfb, never on :0. It prompts for Domain (press Enter) and password, and disconnects after 90 s. The session stays until logged out.

## Rollback

Run as `minerva` with sudo. Order matters: purge xrdp, xorgxrdp, and the XFCE packages first, then autoremove.

```bash
set -e
sudo systemctl disable --now xrdp xrdp-sesman
sudo apt-get purge -y xrdp xorgxrdp
sudo apt-get purge -y xfce4-session xfwm4 xfce4-panel xfdesktop4 xfce4-settings xfce4-terminal thunar dbus-x11 freerdp3-x11 xvfb x11-apps
sudo apt-get autoremove --purge   # interactive: review the list before confirming
sudo rm -rf /etc/xrdp /etc/systemd/system/xrdp.service.d
sudo rm -f /etc/polkit-1/rules.d/45-xrdp-no-popups.rules
sudo systemctl daemon-reload
rm -f ~/.config/xfce4/xfconf/xfce-perchannel-xml/{xsettings,xfwm4,xfce4-panel,xfce4-desktop,xfce4-session}.xml
rm -f ~/.config/autostart/{localsearch-3,geoclue-demo-agent,print-applet}.desktop ~/.local/bin/xrdp-test-connect
```

The `xrdp` system user may remain after purge, and it stays in group `ssl-cert`. Run `sudo deluser xrdp` if you want it gone.

## Caveats

- Same user in both sessions: they share $HOME and /run/user/1000 (pipewire, keyring, podman).
  - The remote session has its own D-Bus, so apps talk to remote-session services only.
  - Single-instance apps cannot run in both sessions at once. Chromium with the kiosk's profile must not be launched in XFCE. If needed, use `chromium --user-data-dir=~/.config/chromium-rdp`.
- XFCE's xinitrc tries `dbus-update-activation-environment --systemd`. On the private bus this fails harmlessly. Verified: the systemd --user environment gets no DISPLAY.
- Installing xfce4-session and xfwm4 set the Debian alternatives `x-session-manager=startxfce4` and `x-window-manager=xfwm4`. The kiosk does not use them (it uses an explicit ~/.xinitrc).
- `/etc/X11/default-display-manager` still points to the stale `/usr/sbin/gdm3` (not installed). Unchanged.
- xrdp does not do NLA. Security is TLS plus PAM password, and the service is reachable only via Tailscale.
