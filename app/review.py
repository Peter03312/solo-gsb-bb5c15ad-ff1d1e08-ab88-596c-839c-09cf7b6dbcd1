"""Continuous collision checking of parsed moves against forbidden zones.

A collision occurs when, at any point along a move, the tool tip Z lies
inside the zone's closed Z range *and* the horizontal distance from the
path to the polygon is less than or equal to the tool radius (boundary
contact counts).  Distances are computed exactly along the whole move, so
collisions between endpoints are never missed.
"""

from __future__ import annotations

from .gcode import Move
from .geometry import EPS, dist_arc_to_polygon, dist_segment_to_polygon

ZoneGeom = tuple[int, list[tuple[float, float]], float, float]  # (id, poly, z_min, z_max)


def _segment_hits_zone(
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
    poly: list[tuple[float, float]], zmin: float, zmax: float, radius: float,
) -> bool:
    dz = z1 - z0
    if abs(dz) < EPS:
        if not (zmin - EPS <= z0 <= zmax + EPS):
            return False
        t0, t1 = 0.0, 1.0
    else:
        # restrict the check to the sub-segment where Z is inside [zmin, zmax]
        ta = (zmin - z0) / dz
        tb = (zmax - z0) / dz
        lo, hi = (ta, tb) if ta < tb else (tb, ta)
        t0, t1 = max(0.0, lo), min(1.0, hi)
        if t0 > t1 + EPS:
            return False
        t0 = min(max(t0, 0.0), 1.0)
        t1 = min(max(t1, 0.0), 1.0)
    sx0, sy0 = x0 + t0 * (x1 - x0), y0 + t0 * (y1 - y0)
    sx1, sy1 = x0 + t1 * (x1 - x0), y0 + t1 * (y1 - y0)
    return dist_segment_to_polygon(poly, (sx0, sy0), (sx1, sy1)) <= radius + EPS


def _arc_hits_zone(
    move: Move, poly: list[tuple[float, float]], zmin: float, zmax: float, radius: float
) -> bool:
    # arcs are guaranteed constant-Z by the parser
    if not (zmin - EPS <= move.z0 <= zmax + EPS):
        return False
    return dist_arc_to_polygon(poly, move.arc) <= radius + EPS


def find_first_collision(
    moves: list[Move], zones: list[ZoneGeom], tool_radius: float
) -> tuple[int, int] | None:
    """Return (original line number, zone id) of the first collision, or None.

    Moves are checked in program order; zones in the given (deterministic)
    order within each move.
    """
    for mv in moves:
        for zone_id, poly, zmin, zmax in zones:
            if mv.kind == "line":
                hit = _segment_hits_zone(
                    mv.x0, mv.y0, mv.z0, mv.x1, mv.y1, mv.z1,
                    poly, zmin, zmax, tool_radius,
                )
            else:
                hit = _arc_hits_zone(mv, poly, zmin, zmax, tool_radius)
            if hit:
                return mv.line_no, zone_id
    return None
