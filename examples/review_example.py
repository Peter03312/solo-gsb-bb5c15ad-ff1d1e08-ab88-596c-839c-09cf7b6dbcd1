#!/usr/bin/env python3
"""End-to-end usage example for the CNC forbidden-zone review service.

Usage:
    python3 examples/review_example.py            # expects the API on :8000
    API_URL=http://localhost:8000 python3 examples/review_example.py
"""

import json
import os

import requests

API = os.getenv("API_URL", "http://localhost:8000")


def main() -> None:
    # 1. register a forbidden zone: 10x10 mm square, Z in [-5, 0]
    zone = requests.post(
        f"{API}/zones",
        json={
            "name": "clamp-zone",
            "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "z_min": -5.0,
            "z_max": 0.0,
        },
    ).json()
    print("zone created:", json.dumps(zone, indent=2))

    # 2. review a toolpath that crosses the zone (collision expected)
    gcode = """%
(cross the forbidden square)
G21 G17 G90
G1 Z-2 F500
X20 Y5
G3 X30 Y5 I5 J0
G0 Z5
%"""
    review = requests.post(
        f"{API}/reviews",
        json={
            "zones": [{"zone_id": zone["zone_id"], "version": zone["version"]}],
            "initial_position": {"x": -10.0, "y": 5.0, "z": 0.0},
            "tool_radius": 1.0,
            "gcode": gcode,
        },
    ).json()
    print("review report:", json.dumps(review, indent=2))

    # 3. same XY path but staying above the zone's Z range -> no collision
    safe = requests.post(
        f"{API}/reviews",
        json={
            "zones": [{"zone_id": zone["zone_id"], "version": zone["version"]}],
            "initial_position": {"x": -10.0, "y": 5.0, "z": 1.0},
            "tool_radius": 0.5,
            "gcode": "G21 G90\nG1 X20 Y5 F500\n",
        },
    ).json()
    print("safe review collision flag:", safe["collision"])

    # 4. modify the zone -> a new immutable version; old reports are untouched
    updated = requests.put(
        f"{API}/zones/{zone['zone_id']}",
        json={
            "polygon": [[0, 0], [30, 0], [30, 10], [0, 10]],
            "z_min": -5.0,
            "z_max": 0.0,
        },
    ).json()
    print("zone updated to version:", updated["version"])

    old_report = requests.get(f"{API}/reports/{review['report_id']}").json()
    print("old report still says collision:", old_report["collision"],
          "(zones_used:", old_report["zones_used"], ")")


if __name__ == "__main__":
    main()
