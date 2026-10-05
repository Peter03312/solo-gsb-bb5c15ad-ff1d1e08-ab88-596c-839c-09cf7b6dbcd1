import math

from app.gcode import parse_program
from app.review import find_first_collision

# forbidden zone: 10x10 square at origin, Z in [-5, 0]
ZONE = (1, [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)], -5.0, 0.0)


def check(gcode, radius, zones=(ZONE,), start=(0, 0, 0)):
    moves = parse_program(gcode, *start)
    return find_first_collision(moves, list(zones), radius)


def test_mid_path_collision_not_missed():
    # both endpoints outside the polygon, path crosses it -> must collide
    hit = check("G1 Z-2\nX20 Y5\n", radius=0.0, start=(-10, 5, 0))
    assert hit == (2, 1)


def test_no_collision_when_z_out_of_range():
    assert check("G1 Z1\nX20 Y5\n", radius=1.0, start=(-10, 5, 0)) is None


def test_z_boundary_counts_as_inside():
    # z exactly at z_min (closed range) and path through the polygon
    hit = check("G1 Z-5\nX20 Y5\n", radius=0.0, start=(-10, 5, 0))
    assert hit == (2, 1)


def test_boundary_contact_counts_as_collision():
    # path tangent to the polygon edge x=10 at distance == radius
    hit = check("G1 Z-2\nX12 Y5\n", radius=2.0, start=(12, -5, 0))
    assert hit == (2, 1)
    # just beyond the radius -> no collision
    assert check("G1 Z-2\nX12 Y5\n", radius=1.999, start=(12, -5, 0)) is None


def test_z_change_during_move_enters_zone_midway():
    # plunge from z=5 to z=-5 while crossing the polygon in XY
    hit = check("G1 X5 Y5 Z-5\n", radius=0.0, start=(-5, 5, 5))
    assert hit == (1, 1)
    # Z enters the zone range only where XY is still outside the polygon:
    # z(t) = 5 - 50t is inside [-5, 0] for t in [0.1, 0.2], x(t) in [-6, -2]
    assert check("G1 X30 Y5 Z-45\n", radius=0.0, start=(-10, 5, 5)) is None
    # but with a shallower plunge the in-range portion reaches the boundary x=10
    hit = check("G1 X30 Y5 Z-5\n", radius=0.0, start=(-10, 5, 5))
    assert hit == (1, 1)


def test_arc_collision():
    # quarter arc from (20,-10) to the polygon corner (10,0), centre (10,-10)
    hit = check("G3 X10 Y0 I-10 J0\n", radius=0.5, start=(20, -10, -2))
    assert hit == (1, 1)
    # same shape shifted right so the arc stays well outside the polygon
    assert check("G3 X20 Y0 I-10 J0\n", radius=0.5, start=(30, -10, -2)) is None


def test_full_circle_collision():
    # full circle of radius 3 centred at (12,5) reaches across the edge x=10
    hit = check("G2 I-3 J0\n", radius=0.0, start=(15, 5, -2))
    assert hit == (1, 1)
    # smaller circle centred at (14,5) stays outside
    assert check("G2 I-1 J0\n", radius=0.0, start=(15, 5, -2)) is None


def test_first_collision_in_program_order():
    zones = [
        (1, [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)], -5.0, 0.0),
        (2, [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)], -5.0, 0.0),
    ]
    # line 2 hits zone 2, line 3 hits zone 1 -> first is line 2 / zone 2
    hit = check("G1 Z-2\nX25 Y5\nX5 Y5\n", radius=0.0, zones=zones, start=(25, -5, 0))
    assert hit == (2, 2)


def test_zero_radius_point_contact():
    # point exactly on the boundary with zero-radius tool
    hit = check("G1 Z-2\nX10 Y5\n", radius=0.0, start=(10, -5, 0))
    assert hit == (2, 1)
