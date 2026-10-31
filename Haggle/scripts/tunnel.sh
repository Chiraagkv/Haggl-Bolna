#!/usr/bin/env bash
# Expose your local backend so Bolna's webhooks can reach it (ticket #4).
# Usage: bash scripts/tunnel.sh [port]     (default port 8000)
#
# Start the app first:  uvicorn app.main:app --port 8000
# Then copy the https URL this prints into PUBLIC_BASE_URL in .env, and test it with:
#   curl https://<your-url>/health

PORT="${1:-8000}"

if command -v ngrok >/dev/null 2>&1; then
  echo "Starting ngrok on port ${PORT}. Copy the https 'Forwarding' URL."
  exec ngrok http "${PORT}"
elif command -v cloudflared >/dev/null 2>&1; then
  echo "Starting a Cloudflare quick tunnel on port ${PORT}. Copy the https://*.trycloudflare.com URL."
  exec cloudflared tunnel --url "http://localhost:${PORT}"
else
  echo "Neither ngrok nor cloudflared is installed."
  echo "Install one:"
  echo "  ngrok:       https://ngrok.com/download  (then: ngrok config add-authtoken <token>)"
  echo "  cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi
