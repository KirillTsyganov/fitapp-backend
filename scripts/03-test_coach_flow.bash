#!/usr/bin/env bash
# End-to-end check: POST /api/coach/flow (hamstrings, TARGET_MINUTES, default 20), then confirm it is listed by GET /api/coach/flows.
# Needs: server running with OPENAI_API_KEY, an existing user (see 01-add_user.bash), jq, and PyJWT (flask venv).
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:5000}"
USER_ID="${USER_ID:-1}"
TARGET_MINUTES="${TARGET_MINUTES:-20}"  # any 5-45
JWT_SECRET_KEY="${JWT_SECRET_KEY:-development-secret-key-must-be-at-least-32-bytes-long}"  # must match the server

fail() { echo "FAIL: $1" >&2; exit 1; }

if [[ -z "${TOKEN:-}" ]]; then
  TOKEN=$(JWT_SECRET_KEY="$JWT_SECRET_KEY" USER_ID="$USER_ID" python3 - <<'EOF'
import datetime as dt
import os

import jwt

exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
print(jwt.encode({'sub': os.environ['USER_ID'], 'exp': exp}, os.environ['JWT_SECRET_KEY'], algorithm='HS256'))
EOF
)
fi

echo "# POST /api/coach/flow (hamstrings, ${TARGET_MINUTES} min)"
RESPONSE=$(curl -s -w '\n%{http_code}' -X POST "$BASE_URL/api/coach/flow" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"target_focus\": \"hamstrings\", \"target_duration_minutes\": ${TARGET_MINUTES}}")
STATUS="${RESPONSE##*$'\n'}"
BODY="${RESPONSE%$'\n'*}"
echo "$BODY" | jq
[[ "$STATUS" == "201" ]] || fail "expected HTTP 201, got $STATUS"

# Time bound: target +/-15%.
echo "$BODY" | jq -e --argjson t "$TARGET_MINUTES" '
  (.routine_data.estimated_total_minutes - $t) as $d
  | .duration_minutes == $t
  and ((if $d < 0 then -$d else $d end) * 100 <= $t * 15)
  and (.routine_data.blocks | length) > 0
' > /dev/null || fail "flow is not ${TARGET_MINUTES} min +/-15% with at least one block"

FLOW_ID=$(echo "$BODY" | jq -r '.id')

echo "# GET /api/coach/flows"
curl -s "$BASE_URL/api/coach/flows" -H "Authorization: Bearer $TOKEN" \
  | jq -e --argjson id "$FLOW_ID" 'map(.id) | index($id) != null' > /dev/null \
  || fail "flow $FLOW_ID not found in GET /api/coach/flows"

echo "PASS: flow $FLOW_ID generated, within time bounds, persisted and listed"
