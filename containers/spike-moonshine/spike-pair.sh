#!/usr/bin/env bash
# SPIKE: complete a Moonlight pairing against the running moonshine container.
#   ./spike-pair.sh <PIN> [uniqueid]
#
# This is the moonshine equivalent of core/sunshine_api.pair(), and the
# comparison is the point of spike question 4:
#
#   Sunshine   POST https://localhost:47990/api/pin   HTTPS, self-signed cert,
#              HTTP basic auth with the per-install credentials podstage seeds
#              headlessly into sunshine.conf, JSON body {"pin","name"}.
#   moonshine  POST http://localhost:<base>/submit-pin   plain HTTP on the same
#              port Moonlight talks to, NO auth at all, form body
#              uniqueid=<id>&pin=<pin>.
#
# The uniqueid identifies the pending pairing attempt; Moonlight sends the
# fixed 0123456789ABCDEF, which is why this works without scraping anything.
# moonshine also opens a desktop notification with the PIN page — meaningless
# in a headless container, so the GUI would drive exactly this endpoint.
set -euo pipefail

PIN=${1:?usage: spike-pair.sh <PIN> [uniqueid]}
UNIQUEID=${2:-0123456789ABCDEF}
SANDBOX=${PS_MS_SANDBOX:-homes/spike-scratch}

cd "$(dirname "$0")/../.."

STATE="$SANDBOX/.local/share/moonshine/state.toml"

# Take the port from the config the running session actually wrote, not from a
# default: spike-run.sh shifts the block to base 48989, but a Deck test runs
# with PS_MS_PORT=47989 so Moonlight can add the host by plain IP. Guessing
# wrong here fails with "Could not connect" while the PIN is expiring.
PORT=${PS_MS_PORT:-$(sed -n 's/^port = \([0-9]\+\)$/\1/p' \
    "$SANDBOX/.config/moonshine/config.toml" 2>/dev/null | head -1)}
PORT=${PORT:-48989}

echo "== paired state before"
grep -E 'clients|paired_certs|unique_id' -A 2 "$STATE" 2>/dev/null || echo "   (no state.toml yet)"

echo "== POST http://localhost:$PORT/submit-pin"
curl -sS -X POST "http://localhost:$PORT/submit-pin" \
    -d "uniqueid=$UNIQUEID&pin=$PIN" -w '\n   http %{http_code}\n'

sleep 2
echo "== paired state after"
grep -E 'clients|paired_certs' -A 2 "$STATE" 2>/dev/null || echo "   (no state.toml)"
