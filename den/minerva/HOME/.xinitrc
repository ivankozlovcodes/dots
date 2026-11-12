xset s off
xset -dpms

# Hide the cursor instantly
unclutter -idle 0 &

exec /usr/bin/chromium \
  --kiosk \
  --no-sandbox \
  --no-first-run \
  --window-size=1280,400 \
  --window-position=0,0 \
  http://localhost:8083
