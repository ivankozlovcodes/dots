#!/bin/sh
# xrdp remote session for minerva: minimal XFCE on its OWN D-Bus session bus.
#
# Deliberately does NOT source ~/.profile, ~/.bash_profile or /etc/X11/Xsession:
# the local kiosk on tty1 is started from ~/.profile / ~/.bash_profile (startx),
# and Xsession would read ~/.xsession. Only XFCE reads ~/.config/xfce4, so the
# remote-session settings never touch the kiosk on :0.

# Safety: xrdp displays start at :10. Never run on the local kiosk display.
case "${DISPLAY:-}" in
  ""|:0|:0.*|unix:0|unix:0.*)
    echo "startwm.sh: refusing to start on DISPLAY='${DISPLAY:-}'" >&2
    exit 1 ;;
esac

if [ -r /etc/profile ]; then
  . /etc/profile
fi
PATH="$HOME/.local/bin:$PATH"
export PATH

# Same user as the kiosk: keep the shared runtime dir (pipewire, keyring...),
# but never reuse the kiosk's session bus (/run/user/UID/bus).
if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -d "/run/user/$(id -u)" ]; then
  XDG_RUNTIME_DIR="/run/user/$(id -u)"
  export XDG_RUNTIME_DIR
fi
unset DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER
XDG_SESSION_TYPE=x11
XRDP_SESSION=1
export XDG_SESSION_TYPE XRDP_SESSION

# No X screensaver blanking / DPMS inside the remote session.
xset s off -dpms 2>/dev/null || true

exec dbus-run-session -- startxfce4
