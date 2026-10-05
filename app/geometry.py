"""2D computational geometry for forbidden-zone collision checks.

All coordinates are millimetres.  Polygons are simple closed rings given as a
list of ``(x, y)`` vertices; the ring is implicitly closed (last -> first).
Boundary contact counts as a collision everywhere in this module, so all
comparisons use ``<=`` with a small epsilon.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-9
TAU = 2.0 * math.pi
_ANG_EPS = 1e-9


class GeometryError(ValueError):
    """Raised when a forbidden-zone polygon is not a valid simple polygon."""


# ------------------------------------------------------------------ polygons

def _signed_area(points: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def validate_polygon(points: list[tuple[float, float]]) -> None:
    """Reject illegal polygon geometry (raises GeometryError)."""
    if len(points) < 3:
        raise GeometryError("polygon needs at least 3 vertices")
    for i, (x, y) in enumerate(points):
        if not (math.isfinite(x) and math.isfinite(y)):
            raise GeometryError(f"vertex {i} is not finite")
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        if math.hypot(x2 - x1, y2 - y1) < EPS:
            raise GeometryError(f"degenerate (zero-length) edge at vertex {i}")
    # non-adjacent edges must not touch or cross (simple polygon)
    for i in range(n):
        a1, a2 = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            if (i + 1) % n == j or (j + 1) % n == i:
                continue  # adjacent edges share exactly one vertex
            b1, b2 = points[j], points[(j + 1) % n]
            if segments_intersect(a1, a2, b1, b2):
                raise GeometryError(
                    f"polygon edges {i} and {j} intersect (self-intersecting polygon)"
                )
    if abs(_signed_area(points)) < EPS:
        raise GeometryError("polygon has zero area")


# ----------------------------------------------------------------- segments

def _orient(p1, p2, p3) -> float:
    return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])


def _on_segment(p, a, b) -> bool:
    if abs(_orient(a, b, p)) > EPS:
        return False
    return (
        min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS
        and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS
    )


def segments_intersect(p1, p2, p3, p4) -> bool:
    o1 = _orient(p1, p2, p3)
    o2 = _orient(p1, p2, p4)
    o3 = _orient(p3, p4, p1)
    o4 = _orient(p3, p4, p2)
    if ((o1 > EPS and o2 < -EPS) or (o1 < -EPS and o2 > EPS)) and (
        (o3 > EPS and o4 < -EPS) or (o3 < -EPS and o4 > EPS)
    ):
        return True
    if abs(o1) <= EPS and _on_segment(p3, p1, p2):
        return True
    if abs(o2) <= EPS and _on_segment(p4, p1, p2):
        return True
    if abs(o3) <= EPS and _on_segment(p1, p3, p4):
        return True
    if abs(o4) <= EPS and _on_segment(p2, p3, p4):
        return True
    return False


def dist_point_to_segment(px: float, py: float, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < EPS:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dist_segment_to_segment(p1, p2, p3, p4) -> float:
    if segments_intersect(p1, p2, p3, p4):
        return 0.0
    return min(
        dist_point_to_segment(p1[0], p1[1], p3, p4),
        dist_point_to_segment(p2[0], p2[1], p3, p4),
        dist_point_to_segment(p3[0], p3[1], p1, p2),
        dist_point_to_segment(p4[0], p4[1], p1, p2),
    )


def point_in_polygon(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting test; points on the boundary count as inside."""
    n = len(poly)
    inside = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if _on_segment((px, py), (x1, y1), (x2, y2)):
            return True
        if (y1 > py) != (y2 > py):
            x_cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if x_cross > px:
                inside = not inside
    return inside


# ---------------------------------------------------------------------- arcs

@dataclass(frozen=True)
class Arc:
    """Circular arc in the XY plane (constant Z).

    ``sweep`` is signed: positive for CCW (G3), negative for CW (G2).
    A full circle has ``abs(sweep) == 2*pi``.
    """

    cx: float
    cy: float
    r: float
    start_angle: float
    sweep: float
    x0: float
    y0: float
    x1: float
    y1: float


def _angle_on_arc(arc: Arc, ang: float) -> bool:
    if arc.sweep > 0:
        return (ang - arc.start_angle) % TAU <= arc.sweep + _ANG_EPS
    return (arc.start_angle - ang) % TAU <= -arc.sweep + _ANG_EPS


def dist_point_to_arc(px: float, py: float, arc: Arc) -> float:
    best = min(
        math.hypot(px - arc.x0, py - arc.y0),
        math.hypot(px - arc.x1, py - arc.y1),
    )
    dx, dy = px - arc.cx, py - arc.cy
    d = math.hypot(dx, dy)
    if d > EPS:
        ang = math.atan2(dy, dx)
        if _angle_on_arc(arc, ang):
            best = min(best, abs(d - arc.r))
    return best


def _segment_crosses_arc(a, b, arc: Arc) -> bool:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    fx, fy = ax - arc.cx, ay - arc.cy
    qa = dx * dx + dy * dy
    if qa < EPS:
        return False  # degenerate segment; endpoint distances cover it
    qb = 2.0 * (fx * dx + fy * dy)
    qc = fx * fx + fy * fy - arc.r * arc.r
    disc = qb * qb - 4.0 * qa * qc
    if disc < -EPS:
        return False
    disc = max(0.0, disc)
    root = math.sqrt(disc)
    for t in ((-qb - root) / (2.0 * qa), (-qb + root) / (2.0 * qa)):
        if -EPS <= t <= 1.0 + EPS:
            px, py = ax + t * dx, ay + t * dy
            ang = math.atan2(py - arc.cy, px - arc.cx)
            if _angle_on_arc(arc, ang):
                return True
    return False


def dist_arc_to_segment(arc: Arc, a, b) -> float:
    """Exact minimum distance between an arc and a line segment."""
    if _segment_crosses_arc(a, b, arc):
        return 0.0
    candidates = [
        dist_point_to_segment(arc.x0, arc.y0, a, b),
        dist_point_to_segment(arc.x1, arc.y1, a, b),
        dist_point_to_arc(a[0], a[1], arc),
        dist_point_to_arc(b[0], b[1], arc),
    ]
    # Interior-interior minima occur where the circle normal is perpendicular
    # to the segment, i.e. at the two circle points along the segment normal.
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length > EPS:
        nx, ny = -dy / length, dx / length
        for s in (1.0, -1.0):
            px = arc.cx + s * arc.r * nx
            py = arc.cy + s * arc.r * ny
            ang = math.atan2(py - arc.cy, px - arc.cx)
            if _angle_on_arc(arc, ang):
                candidates.append(dist_point_to_segment(px, py, a, b))
    return min(candidates)


# ------------------------------------------------- path <-> polygon distance

def dist_segment_to_polygon(poly: list[tuple[float, float]], p1, p2) -> float:
    if point_in_polygon(p1[0], p1[1], poly) or point_in_polygon(p2[0], p2[1], poly):
        return 0.0
    n = len(poly)
    best = math.inf
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        best = min(best, dist_segment_to_segment(p1, p2, a, b))
        if best <= EPS:
            return 0.0
    return best


def dist_arc_to_polygon(poly: list[tuple[float, float]], arc: Arc) -> float:
    if point_in_polygon(arc.x0, arc.y0, poly):
        return 0.0
    n = len(poly)
    best = math.inf
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        best = min(best, dist_arc_to_segment(arc, a, b))
        if best <= EPS:
            return 0.0
    return best
