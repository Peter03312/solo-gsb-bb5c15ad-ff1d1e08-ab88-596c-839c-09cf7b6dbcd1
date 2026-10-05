import math

import pytest

from app.geometry import (
    Arc,
    GeometryError,
    dist_arc_to_polygon,
    dist_point_to_arc,
    dist_segment_to_polygon,
    point_in_polygon,
    validate_polygon,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_validate_polygon_ok():
    validate_polygon(SQUARE)
    validate_polygon([(0, 0), (4, 0), (2, 3)])  # triangle


def test_validate_polygon_rejects_bad_geometry():
    with pytest.raises(GeometryError):
        validate_polygon([(0, 0), (1, 1)])  # too few vertices
    with pytest.raises(GeometryError):
        validate_polygon([(0, 0), (0, 0), (1, 0), (1, 1)])  # degenerate edge
    with pytest.raises(GeometryError):
        # bow-tie / self-intersecting
        validate_polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
    with pytest.raises(GeometryError):
        validate_polygon([(0, 0), (1, 0), (2, 0)])  # zero area
    with pytest.raises(GeometryError):
        validate_polygon([(0, 0), (1, 0), (float("nan"), 1)])


def test_point_in_polygon():
    assert point_in_polygon(5, 5, SQUARE)
    assert not point_in_polygon(15, 5, SQUARE)
    assert point_in_polygon(0, 5, SQUARE)  # boundary counts as inside
    assert point_in_polygon(10, 10, SQUARE)  # corner


def test_segment_to_polygon_distance():
    # fully outside
    assert dist_segment_to_polygon(SQUARE, (20, 0), (20, 10)) == pytest.approx(10.0)
    # crossing the polygon -> 0 even though both endpoints are outside
    assert dist_segment_to_polygon(SQUARE, (-5, 5), (15, 5)) == 0.0
    # endpoint inside
    assert dist_segment_to_polygon(SQUARE, (5, 5), (20, 5)) == 0.0
    # diagonal gap: segment from (12,12) to (15,15), nearest corner (10,10)
    assert dist_segment_to_polygon(SQUARE, (12, 12), (15, 15)) == pytest.approx(
        math.hypot(2, 2)
    )


def _arc(cx, cy, r, a0_deg, sweep_deg):
    a0 = math.radians(a0_deg)
    sw = math.radians(sweep_deg)
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    a1 = a0 + sw
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    return Arc(cx, cy, r, a0, sw, x0, y0, x1, y1)


def test_point_to_arc():
    arc = _arc(0, 0, 10, 0, 90)  # quarter circle in first quadrant
    assert dist_point_to_arc(20, 0, arc) == pytest.approx(10.0)
    assert dist_point_to_arc(0, 20, arc) == pytest.approx(10.0)
    # point on the arc
    assert dist_point_to_arc(10 / math.sqrt(2), 10 / math.sqrt(2), arc) == pytest.approx(0.0)
    # point closest to an endpoint when projection is off the arc
    assert dist_point_to_arc(0, -5, arc) == pytest.approx(math.hypot(10, 5))


def test_arc_to_polygon():
    # arc entirely outside, nearest approach along the x axis
    arc = _arc(20, 5, 5, 90, 180)  # left half of circle at (20,5) r=5
    assert dist_arc_to_polygon(SQUARE, arc) == pytest.approx(5.0)
    # arc crossing the polygon edge x=10 (circle r=6 around (5,5) crosses
    # the edge at y = 5 +/- sqrt(11), both inside the edge's span)
    arc = _arc(5, 5, 6, 0, 90)
    assert dist_arc_to_polygon(SQUARE, arc) == 0.0
    # arc fully inside the polygon
    arc = _arc(5, 5, 2, 0, 360)
    assert dist_arc_to_polygon(SQUARE, arc) == 0.0
    # full circle around the polygon, radius 20 centred inside
    arc = _arc(5, 5, 20, 0, 360)
    assert dist_arc_to_polygon(SQUARE, arc) == pytest.approx(20 - 5 * math.sqrt(2))


def test_full_circle_distance():
    arc = _arc(30, 0, 10, 0, -360)  # clockwise full circle
    assert dist_arc_to_polygon(SQUARE, arc) == pytest.approx(10.0)
