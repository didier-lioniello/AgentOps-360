#!/usr/bin/env bash
# End-to-end demo: register two versions, set a canary policy, invoke a few times.
set -euo pipefail

API="${API:-http://localhost:8000}"
DEV_TOKEN="${DEV_TOKEN:-local-demo-token-only}"
AUTH="Authorization: Bearer ${DEV_TOKEN}"
JSON="Content-Type: application/json"

echo "==> Register v1.0.0"
curl -fsS -X POST "$API/v1/agents" -H "$AUTH" -H "$JSON" \
  -d @examples/agents/orders_classifier_v1.json | jq .

echo "==> Register v1.1.0-canary"
curl -fsS -X POST "$API/v1/agents" -H "$AUTH" -H "$JSON" \
  -d @examples/agents/orders_classifier_v2_canary.json | jq .

echo "==> Apply 90/10 canary routing policy"
curl -fsS -X PUT "$API/v1/routing/orders-classifier" -H "$AUTH" -H "$JSON" \
  -d @examples/routing/orders_canary.json | jq .

echo "==> Invoke with three different inputs"
for msg in "my order #4421 never arrived" "wrong color sent in box 8821" "I want my money back"; do
  curl -fsS -X POST "$API/v1/invoke" -H "$AUTH" -H "$JSON" \
    -d "{\"agent\":\"orders-classifier\",\"input\":\"$msg\"}" | jq .
done

echo "==> List recent invocations for tenant 'acme'"
curl -fsS "$API/v1/traces/invocations?limit=5" -H "$AUTH" | jq .
