xset s 1800
xset dpms 1800 1800 1800
exec /usr/bin/chromium \
  --kiosk \
  --no-sandbox \
  --no-first-run \
  --window-size=1280,400 \
  --window-position=0,0 \
  http://localhost:8083
