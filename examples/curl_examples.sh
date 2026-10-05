#!/usr/bin/env bash
# curl examples for the CNC forbidden-zone review service (API on :8000)
set -euo pipefail
API="${API_URL:-http://localhost:8000}"

echo "== health =="
curl -s "$API/health"; echo

echo "== create zone (version 1) =="
ZONE=$(curl -s -X POST "$API/zones" -H 'Content-Type: application/json' -d '{
  "name": "clamp-zone",
  "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
  "z_min": -5.0,
  "z_max": 0.0
}')
echo "$ZONE"
ZONE_ID=$(echo "$ZONE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["zone_id"])')

echo "== review: path crosses the zone -> collision =="
curl -s -X POST "$API/reviews" -H 'Content-Type: application/json' -d "{
  \"zones\": [{\"zone_id\": $ZONE_ID, \"version\": 1}],
  \"initial_position\": {\"x\": -10, \"y\": 5, \"z\": 0},
  \"tool_radius\": 1.0,
  \"gcode\": \"G21 G17 G90\nG1 Z-2 F500\nX20 Y5\nG0 Z5\n\"
}"; echo

echo "== review: illegal G-code -> 422, no report stored =="
curl -s -X POST "$API/reviews" -H 'Content-Type: application/json' -d "{
  \"zones\": [{\"zone_id\": $ZONE_ID, \"version\": 1}],
  \"initial_position\": {\"x\": 0, \"y\": 0, \"z\": 0},
  \"tool_radius\": 1.0,
  \"gcode\": \"G18\nG1 X1\n\"
}"; echo

echo "== update zone -> immutable version 2 =="
curl -s -X PUT "$API/zones/$ZONE_ID" -H 'Content-Type: application/json' -d '{
  "polygon": [[0, 0], [30, 0], [30, 10], [0, 10]],
  "z_min": -5.0,
  "z_max": 0.0
}'; echo

echo "== old version still available =="
curl -s "$API/zones/$ZONE_ID/versions/1"; echo

echo "== all reports =="
curl -s "$API/reports"; echo
