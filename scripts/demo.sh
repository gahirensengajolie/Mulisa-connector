#!/usr/bin/env bash
# Runs every scenario from the brief. Needs the mock and the connector running (see README),
# and CONNECTOR_KEY set to one of the keys in CONNECTOR_API_KEYS.
set -u
CONNECTOR="${CONNECTOR_URL:-http://localhost:8000}"
MOCK="${MOCK_URL:-http://localhost:9100}"
KEY="${CONNECTOR_KEY:?set CONNECTOR_KEY to your connector API key}"
RUN=$(date +%s)   # unique references per run, so the demo can be repeated

payment() {  # $1 = key in data/payments.json, $2 = suffix. Prints the JSON with a fresh reference.
  python3 - "$1" "$2" <<PY
import json, sys
d = json.load(open("data/payments.json"))[sys.argv[1]]
d["reference"] = f"GB-DEMO-$RUN-{sys.argv[2]}"
print(json.dumps(d))
PY
}
screen() { curl -s -w '\n-> HTTP %{http_code}\n' -X POST "$CONNECTOR/payments/screen" \
  -H "X-Api-Key: $KEY" -H 'Content-Type: application/json' -d "$1"; }
mode() { curl -s -X POST "$MOCK/__control" -H 'Content-Type: application/json' -d "$1" >/dev/null; }
say() { printf '\n== %s\n' "$1"; }

mode '{"mode":"normal"}'
say "1. Cleared payment";                     screen "$(payment cleared a)"
say "2a. Flagged: high value";                screen "$(payment flagged_high_value b)"
say "2b. Flagged: blacklisted wallet";        screen "$(payment flagged_blacklisted_wallet c)"
say "3. KES (two decimals -> minor units)";   screen "$(payment kes_two_decimals d)"
say "4. Malformed input";                     screen "$(payment malformed_amount_is_a_float e)"
say "5. Duplicate (second answer: replayed true)"
P="$(payment cleared f)"; screen "$P"; screen "$P"
say "6. Same reference, different amount -> 409"
screen "$(echo "$P" | sed 's/"250000"/"999"/')"
say "7. Wrong key -> 401"
curl -s -w '\n-> HTTP %{http_code}\n' -X POST "$CONNECTOR/payments/screen" -H 'X-Api-Key: nope' -H 'Content-Type: application/json' -d "$P"
say "8. Timeout on the first call, retry succeeds (flaky_once)"
mode '{"mode":"flaky_once","delay":5}'; screen "$(payment cleared g)"
say "9. Mulisa keeps timing out -> bank policy decides"
mode '{"mode":"slow","delay":5}'; screen "$(payment cleared h)"
say "10. Mulisa returns 503 (retryable) -> one retry, then policy"
mode '{"mode":"error_503"}'; screen "$(payment cleared i)"
say "11. Mulisa recovers: the same reference is now really screened"
mode '{"mode":"normal"}'; screen "$(payment cleared i)"
say "Mock stats (requests vs processed shows idempotency)"
curl -s "$MOCK/__stats" | python3 -c "import json,sys; d=json.load(sys.stdin); print({k:d[k] for k in ('requests','processed')})"
