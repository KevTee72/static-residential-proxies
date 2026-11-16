#!/usr/bin/env bash
# curl recipes for a static residential proxy.
# Fill in the four values from the proxy details page in the dashboard.
#
#   PROXY_HOST=203.0.113.10 PROXY_PORT=12345 PROXY_USER=... PROXY_PASS=... ./curl_examples.sh

set -euo pipefail

: "${PROXY_HOST:?set PROXY_HOST to the proxy IP}"
: "${PROXY_PORT:?set PROXY_PORT to the proxy port}"
PROXY_USER="${PROXY_USER:-}"
PROXY_PASS="${PROXY_PASS:-}"
ECHO_URL="${ECHO_URL:-https://ipv4.icanhazip.com}"

AUTH=()
if [ -n "$PROXY_USER" ]; then
  AUTH=(-U "$PROXY_USER:$PROXY_PASS")
fi

echo "1. HTTP proxy, username and password (or IP whitelist when PROXY_USER is empty)"
curl -sS -x "http://$PROXY_HOST:$PROXY_PORT" "${AUTH[@]}" "$ECHO_URL"

echo "2. Same IP three times in a row"
for attempt in 1 2 3; do
  curl -sS -x "http://$PROXY_HOST:$PROXY_PORT" "${AUTH[@]}" "$ECHO_URL"
done

echo "3. Timing through the proxy"
curl -sS -o /dev/null -x "http://$PROXY_HOST:$PROXY_PORT" "${AUTH[@]}" \
  -w "connect %{time_connect}s  first byte %{time_starttransfer}s  total %{time_total}s\n" "$ECHO_URL"

# The next two only work after the proxy protocol is switched to SOCKS5 in the
# dashboard or with POST /proxies/{id}/change-protocol. The port changes with it.
if [ "${PROXY_PROTOCOL:-HTTP}" = "SOCKS5" ]; then
  echo "4. SOCKS5, hostname resolved on your machine"
  curl -sS -x "socks5://$PROXY_HOST:$PROXY_PORT" "${AUTH[@]}" "$ECHO_URL"

  echo "5. SOCKS5H, hostname resolved by the proxy"
  curl -sS -x "socks5h://$PROXY_HOST:$PROXY_PORT" "${AUTH[@]}" "$ECHO_URL"
fi
