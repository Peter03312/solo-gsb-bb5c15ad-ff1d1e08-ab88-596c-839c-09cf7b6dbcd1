import math

import pytest

from app.gcode import GCodeError, parse_program


def test_linear_moves_and_modal_state():
    moves = parse_program(
        "G21 G17 G90\n"
        "G0 X10 Y0\n"
        "G1 X10 Y10 F500\n"
        "X20\n"  # modal G1, missing axes inherit previous values
        "Z-5\n",
        0, 0, 0,
    )
    assert [(m.x0, m.y0, m.z0, m.x1, m.y1, m.z1) for m in moves] == [
        (0, 0, 0, 10, 0, 0),
        (10, 0, 0, 10, 10, 0),
        (10, 10, 0, 20, 10, 0),
        (20, 10, 0, 20, 10, -5),
    ]
    assert [m.line_no for m in moves] == [2, 3, 4, 5]


def test_incremental_mode():
    moves = parse_program("G91\nG1 X10 Y5\nX5\n", 0, 0, 0)
    assert (moves[0].x1, moves[0].y1) == (10, 5)
    assert (moves[1].x1, moves[1].y1) == (15, 5)


def test_inches_converted_to_mm():
    moves = parse_program("G20\nG1 X1\nG21\nX2\n", 0, 0, 0)
    assert moves[0].x1 == pytest.approx(25.4)
    assert moves[1].x1 == pytest.approx(2.0)  # absolute mode: go to x=2 mm


def test_line_numbers_track_original_text():
    moves = parse_program(
        "%\n(comment line)\n\n; trailing comment\nG1 X5 ; move\n",
        0, 0, 0,
    )
    assert len(moves) == 1
    assert moves[0].line_no == 5


def test_arc_quarter_ccw():
    moves = parse_program("G3 X20 Y10 I0 J10\n", 10, 0, 0)
    arc = moves[0].arc
    assert (arc.cx, arc.cy, arc.r) == (10, 10, 10)
    assert arc.sweep == pytest.approx(math.pi / 2)
    assert (moves[0].x1, moves[0].y1) == (20, 10)


def test_arc_full_circle_same_start_end():
    moves = parse_program("G2 X5 Y5 I-5 J0\n", 5, 5, 0)
    assert moves[0].arc.sweep == pytest.approx(-2 * math.pi)
    # no X/Y at all with I/J is also a full circle
    moves = parse_program("G3 I4\n", 0, 0, 0)
    assert moves[0].arc.sweep == pytest.approx(2 * math.pi)
    assert moves[0].arc.r == pytest.approx(4)


def test_arc_modal_and_ij_relative_to_start():
    moves = parse_program("G2 X10 Y0 I5 J0\nX20 Y0 I5\n", 0, 0, 0)
    assert moves[0].arc.cx == 5
    assert moves[1].arc.cx == 15  # I relative to the new start (10, 0)


def test_arc_in_incremental_mode():
    moves = parse_program("G91\nG3 X10 I5\n", 0, 0, 0)
    assert (moves[0].x1, moves[0].y1) == (10, 0)
    assert moves[0].arc.sweep == pytest.approx(math.pi)


def test_rejects_illegal_and_unsupported():
    bad = [
        "G18\n",               # unsupported plane
        "G4 P1\n",             # unsupported G code (dwell)
        "G54\n",               # unsupported coordinate-system command
        "G1 X1 Q2\n",          # unknown word
        "G2 X1 Y1 R5\n",       # R-format arcs not supported
        "G2 X1 Y1\n",          # arc without I/J -> zero radius
        "G2 X3 Y0 I1 J0\n",    # end point not on the circle
        "G2 X1 Y0 I0.5 Z-2\n", # helical arc
        "G1.5 X1\n",           # non-integer G code
        "G1 X1 $\n",           # garbage token
        "G1 X1 (oops\n",       # unterminated comment
    ]
    for text in bad:
        with pytest.raises(GCodeError):
            parse_program(text, 0, 0, 0)


def test_error_carries_line_number():
    with pytest.raises(GCodeError) as exc:
        parse_program("G1 X1\nG1 X2\nG18\n", 0, 0, 0)
    assert exc.value.line_no == 3


def test_constant_z_word_on_arc_allowed():
    moves = parse_program("G1 Z-5\nG2 X10 Y0 I5 J0 Z-5\n", 0, 0, -5)
    assert moves[-1].kind == "arc"
    assert moves[-1].z0 == moves[-1].z1 == -5


def test_ignored_words_and_comments():
    moves = parse_program(
        "N10 T1 M6 S1000 F500 (tool change)\nN20 G1 X10 M3\n",
        0, 0, 0,
    )
    assert len(moves) == 1
    assert moves[0].line_no == 2
