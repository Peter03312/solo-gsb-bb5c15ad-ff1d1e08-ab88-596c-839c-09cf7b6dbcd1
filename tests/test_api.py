import os
import tempfile

# point the app at a throwaway SQLite database before importing it
_tmpdir = tempfile.mkdtemp(prefix="cnc_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)

ZONE_BODY = {
    "name": "box",
    "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
    "z_min": -5,
    "z_max": 0,
}


def _create_zone(body=None):
    resp = client.post("/zones", json=body or ZONE_BODY)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _review(zone_id, version, gcode, radius=1.0, start=None):
    return client.post(
        "/reviews",
        json={
            "zones": [{"zone_id": zone_id, "version": version}],
            "initial_position": start or {"x": -10, "y": 5, "z": 0},
            "tool_radius": radius,
            "gcode": gcode,
        },
    )


def test_zone_create_and_versioning():
    zone = _create_zone()
    assert zone["version"] == 1 and zone["current_version"] == 1

    updated = client.put(
        f"/zones/{zone['zone_id']}",
        json={"polygon": [[0, 0], [20, 0], [20, 20], [0, 20]], "z_min": -8, "z_max": 1},
    )
    assert updated.status_code == 201
    assert updated.json()["version"] == 2

    # old version is still retrievable and unchanged
    v1 = client.get(f"/zones/{zone['zone_id']}/versions/1")
    assert v1.status_code == 200
    assert v1.json()["polygon"] == [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert v1.json()["z_min"] == -5

    versions = client.get(f"/zones/{zone['zone_id']}/versions").json()
    assert versions == [1, 2]


def test_invalid_polygon_rejected():
    bad = client.post(
        "/zones",
        json={"polygon": [[0, 0], [2, 2], [2, 0], [0, 2]], "z_min": 0, "z_max": 1},
    )
    assert bad.status_code == 422
    bad_z = client.post(
        "/zones",
        json={"polygon": [[0, 0], [1, 0], [1, 1]], "z_min": 2, "z_max": 1},
    )
    assert bad_z.status_code == 422


def test_review_no_collision():
    zone = _create_zone()
    resp = _review(zone["zone_id"], 1, "G1 Z1\nX30 Y5\n", radius=1.0)
    assert resp.status_code == 201, resp.text
    report = resp.json()
    assert report["collision"] is False
    assert report["collision_line"] is None
    assert report["collision_zone_id"] is None
    assert report["zones_used"] == [{"zone_id": zone["zone_id"], "version": 1}]
    assert report["input_summary"]["tool_radius"] == 1.0
    assert report["input_summary"]["initial_position"] == {"x": -10, "y": 5, "z": 0}
    assert report["input_summary"]["gcode_lines"] == 2
    assert len(report["input_summary"]["gcode_sha256"]) == 64

    fetched = client.get(f"/reports/{report['report_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == report


def test_review_collision_reports_line_and_zone():
    zone = _create_zone()
    resp = _review(
        zone["zone_id"], 1,
        "(comment)\nG21 G90\nG1 Z-2\nX20 Y5\n",
        radius=0.5,
    )
    assert resp.status_code == 201
    report = resp.json()
    assert report["collision"] is True
    assert report["collision_line"] == 4  # original line number
    assert report["collision_zone_id"] == zone["zone_id"]


def test_invalid_gcode_rejected_without_report():
    zone = _create_zone()
    before = len(client.get("/reports").json())
    resp = _review(zone["zone_id"], 1, "G1 X1\nG18\n")
    assert resp.status_code == 422
    assert resp.json()["detail"]["line"] == 2
    after = client.get("/reports").json()
    assert len(after) == before  # no report left behind


def test_invalid_radius_rejected_without_report():
    zone = _create_zone()
    before = len(client.get("/reports").json())
    resp = _review(zone["zone_id"], 1, "G1 X1\n", radius=-0.5)
    assert resp.status_code == 422
    assert len(client.get("/reports").json()) == before


def test_unknown_zone_version_rejected():
    resp = _review(9999, 1, "G1 X1\n")
    assert resp.status_code == 404


def test_reports_are_immutable_across_zone_updates():
    zone = _create_zone()
    # path runs 5 mm to the right of the v1 polygon (x in [15, 25]): safe for v1
    start = {"x": 15, "y": 5, "z": 0}
    resp = _review(zone["zone_id"], 1, "G1 Z-2\nX25 Y5\n", radius=1.0, start=start)
    assert resp.json()["collision"] is False
    report_id = resp.json()["report_id"]

    # enlarge the zone so the same path now collides
    client.put(
        f"/zones/{zone['zone_id']}",
        json={"polygon": [[0, 0], [30, 0], [30, 10], [0, 10]], "z_min": -5, "z_max": 0},
    )
    # old report must not change
    old = client.get(f"/reports/{report_id}").json()
    assert old["collision"] is False
    assert old["zones_used"] == [{"zone_id": zone["zone_id"], "version": 1}]

    # a new review pinned to the old version still says no collision
    again = _review(zone["zone_id"], 1, "G1 Z-2\nX25 Y5\n", radius=1.0, start=start)
    assert again.json()["collision"] is False
    # and pinned to the new version it collides
    newer = _review(zone["zone_id"], 2, "G1 Z-2\nX25 Y5\n", radius=1.0, start=start)
    assert newer.json()["collision"] is True


def test_multi_zone_review():
    z1 = _create_zone()
    z2 = _create_zone(
        {"polygon": [[20, 0], [30, 0], [30, 10], [20, 10]], "z_min": -5, "z_max": 0}
    )
    resp = client.post(
        "/reviews",
        json={
            "zones": [
                {"zone_id": z1["zone_id"], "version": 1},
                {"zone_id": z2["zone_id"], "version": 1},
            ],
            "initial_position": {"x": 25, "y": -5, "z": -2},
            "tool_radius": 0.0,
            "gcode": "G1 Y5\n",
        },
    )
    assert resp.status_code == 201
    report = resp.json()
    assert report["collision"] is True
    assert report["collision_zone_id"] == z2["zone_id"]
    assert report["collision_line"] == 1
