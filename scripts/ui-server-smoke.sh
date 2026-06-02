#!/usr/bin/env bash
# End-to-end smoke of the Dictate UI control server — the exact handshake +
# authenticated contract the Tauri shell relies on. Runs against an isolated
# XDG home so it never touches real user config/history.
#
# Usage: scripts/ui-server-smoke.sh [python]
set -euo pipefail

PYTHON="${1:-.venv/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'kill "${SERVER_PID:-}" 2>/dev/null || true; rm -rf "$TMP"' EXIT
export XDG_DATA_HOME="$TMP/data"
export XDG_CONFIG_HOME="$TMP/config"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME"

HANDSHAKE="$XDG_DATA_HOME/dictate/ui-server.json"

echo "▶ starting dictate-ui-server (isolated XDG home)…"
"$PYTHON" -m dictate.ui_server >"$TMP/server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 50); do
  [ -f "$HANDSHAKE" ] && break
  sleep 0.1
done
if [ ! -f "$HANDSHAKE" ]; then
  echo "✗ server did not write a handshake"; cat "$TMP/server.log"; exit 1
fi

URL="$("$PYTHON" -c "import json,sys;print(json.load(open(sys.argv[1]))['url'])" "$HANDSHAKE")"
TOKEN="$("$PYTHON" -c "import json,sys;print(json.load(open(sys.argv[1]))['token'])" "$HANDSHAKE")"
echo "  handshake: $URL"

fail() { echo "✗ $1"; cat "$TMP/server.log"; exit 1; }

echo "▶ GET /api/health (unauthenticated)…"
curl -fsS "$URL/api/health" | grep -q '"status": *"ok"' || fail "health check failed"

echo "▶ GET /api/state without a token must be 401…"
code="$(curl -s -o /dev/null -w '%{http_code}' "$URL/api/state")"
[ "$code" = "401" ] || fail "expected 401, got $code"

echo "▶ GET /api/state with the bearer token…"
state="$(curl -fsS -H "Authorization: Bearer $TOKEN" "$URL/api/state")"
echo "$state" | grep -q '"backend": *"faster-whisper"' || fail "state missing default backend"

echo "▶ PATCH /api/config sets a preference…"
patched="$(curl -fsS -X PATCH -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"prefs":{"theme":"dark"}}' "$URL/api/config")"
echo "$patched" | grep -q '"theme": *"dark"' || fail "config patch did not persist"

echo "✓ UI server end-to-end smoke passed"
