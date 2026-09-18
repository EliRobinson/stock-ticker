#!/usr/bin/env bash
# Share the local stack on public HTTPS links through Cloudflare quick tunnels.
# Keep this terminal open while people test. Ctrl+C stops sharing and restores
# local-only settings.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v cloudflared >/dev/null || { echo "Install cloudflared first: brew install cloudflared"; exit 1; }
LOGS=$(mktemp -d)

cloudflared tunnel --no-autoupdate --url http://127.0.0.1:3000 >"$LOGS/web.log" 2>&1 &
WEB_PID=$!
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000 >"$LOGS/api.log" 2>&1 &
API_PID=$!

url_from() { grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$1" | head -1; }
for _ in $(seq 60); do
  WEB_URL=$(url_from "$LOGS/web.log" || true)
  API_URL=$(url_from "$LOGS/api.log" || true)
  [ -n "$WEB_URL" ] && [ -n "$API_URL" ] && break
  sleep 1
done
[ -n "${WEB_URL:-}" ] && [ -n "${API_URL:-}" ] || { echo "Tunnels did not start. Logs: $LOGS"; kill $WEB_PID $API_PID; exit 1; }

WEB_HOST=${WEB_URL#https://}
API_HOST=${API_URL#https://}

restore() {
  echo; echo "Stopping tunnels and restoring local-only settings..."
  kill $WEB_PID $API_PID 2>/dev/null || true
  env -u PUBLIC_API_URL -u PUBLIC_WEB_HOST -u WEB_ORIGIN -u ALLOWED_HOSTS docker compose up -d api web >/dev/null
}
trap restore EXIT

PUBLIC_API_URL="$API_URL" PUBLIC_WEB_HOST="$WEB_HOST" WEB_ORIGIN="$WEB_URL" \
  ALLOWED_HOSTS="[\"127.0.0.1\",\"localhost\",\"$API_HOST\"]" \
  docker compose up -d api web >/dev/null

echo "Waiting for the web app to restart..."
until curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/ | grep -q 200; do sleep 3; done

echo
echo "Share this link: $WEB_URL"
echo "API (used by the page): $API_URL"
echo "AI spend is capped at \$5. Press Ctrl+C to stop sharing."
wait
