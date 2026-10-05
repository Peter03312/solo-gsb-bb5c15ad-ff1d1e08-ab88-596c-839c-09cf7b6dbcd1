"""Modal G-code parser producing an ordered list of toolpath moves.

Supported modal groups:
  motion   G0 G1 G2 G3        (default G1; G0/G1 are both linear moves)
  plane    G17                (XY plane only; G18/G19 are rejected)
  units    G20 G21            (G20 values are converted inch -> mm)
  distance G90 G91            (absolute / incremental)

Missing axis words inherit the previous value.  Arcs are XY-plane only and
keep Z constant; I/J are always relative to the arc start point, and an arc
whose end equals its start is a full circle.  Anything else (unknown words,
unsupported G codes, R-format arcs, helical arcs, malformed arcs) raises
GCodeError so the caller can reject the review without storing a report.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .geometry import EPS, Arc

INCH_TO_MM = 25.4
ARC_ENDPOINT_TOL = 1e-3  # mm tolerance between programmed end point and arc circle


class GCodeError(ValueError):
    """Illegal or unsupported G-code; carries the original 1-based line number."""

    def __init__(self, line_no: int, message: str):
        self.line_no = line_no
        self.message = message
        super().__init__(f"line {line_no}: {message}")


@dataclass
class Move:
    line_no: int
    kind: str  # "line" or "arc"
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float
    arc: Arc | None = None


_WORD_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")
_MOTION_G = {0: "G0", 1: "G1", 2: "G2", 3: "G3"}
_SUPPORTED_G = set(_MOTION_G) | {17, 20, 21, 90, 91}
_IGNORED_WORDS = set("MFSTN")  # machine/feed/speed/tool/line-number words


@dataclass
class _State:
    x: float
    y: float
    z: float
    motion: str = "G1"
    plane: str = "G17"
    units: str = "G21"
    distance: str = "G90"


def _strip_comments(line: str, line_no: int) -> str:
    out: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == ";":
            break
        if ch == "(":
            j = line.find(")", i + 1)
            if j < 0:
                raise GCodeError(line_no, "unterminated comment")
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _tokenize(line: str, line_no: int) -> list[tuple[str, str]]:
    words: list[tuple[str, str]] = []
    pos = 0
    for m in _WORD_RE.finditer(line):
        gap = line[pos : m.start()].strip()
        if gap:
            raise GCodeError(line_no, f"unrecognized token '{gap}'")
        words.append((m.group(1).upper(), m.group(2)))
        pos = m.end()
    tail = line[pos:].strip()
    if tail:
        raise GCodeError(line_no, f"unrecognized token '{tail}'")
    if not words:
        raise GCodeError(line_no, "no recognizable words on line")
    return words


def parse_program(text: str, x0: float, y0: float, z0: float) -> list[Move]:
    """Parse G-code text into ordered moves.  Initial position is in mm."""
    st = _State(x0, y0, z0)
    moves: list[Move] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comments(raw, line_no).strip()
        if not line or line == "%":
            continue
        _apply_line(_tokenize(line, line_no), st, moves, line_no)
    return moves


def _apply_line(words: list[tuple[str, str]], st: _State, moves: list[Move], line_no: int) -> None:
    g_codes: list[int] = []
    coords: dict[str, float] = {}
    for letter, value in words:
        if letter == "G":
            f = float(value)
            if not f.is_integer():
                raise GCodeError(line_no, f"unsupported G code G{value}")
            g = int(f)
            if g not in _SUPPORTED_G:
                raise GCodeError(line_no, f"unsupported G code G{g}")
            g_codes.append(g)
        elif letter in "XYZIJ":
            coords[letter] = float(value)
        elif letter in _IGNORED_WORDS:
            continue
        else:
            raise GCodeError(line_no, f"unsupported word {letter}{value}")

    motion_seen = False
    for g in g_codes:
        if g in _MOTION_G:
            st.motion = _MOTION_G[g]
            motion_seen = True
        elif g == 17:
            st.plane = "G17"
        elif g == 20:
            st.units = "G20"
        elif g == 21:
            st.units = "G21"
        elif g == 90:
            st.distance = "G90"
        elif g == 91:
            st.distance = "G91"

    scale = INCH_TO_MM if st.units == "G20" else 1.0
    coords = {k: v * scale for k, v in coords.items()}

    has_axis = any(k in coords for k in "XYZ")
    has_ij = any(k in coords for k in "IJ")
    if not motion_seen and not has_axis and not has_ij:
        return  # pure modal / parameter line, no motion

    if st.motion in ("G0", "G1"):
        _linear_move(coords, st, moves, line_no, has_axis)
    else:
        _arc_move(coords, st, moves, line_no, has_axis or has_ij)


def _linear_move(coords, st, moves, line_no, has_axis) -> None:
    if not has_axis:
        return
    tx, ty, tz = st.x, st.y, st.z
    if st.distance == "G90":
        tx = coords.get("X", tx)
        ty = coords.get("Y", ty)
        tz = coords.get("Z", tz)
    else:
        tx += coords.get("X", 0.0)
        ty += coords.get("Y", 0.0)
        tz += coords.get("Z", 0.0)
    if math.hypot(tx - st.x, ty - st.y) < EPS and abs(tz - st.z) < EPS:
        st.x, st.y, st.z = tx, ty, tz
        return
    moves.append(Move(line_no, "line", st.x, st.y, st.z, tx, ty, tz))
    st.x, st.y, st.z = tx, ty, tz


def _arc_move(coords, st, moves, line_no, has_words) -> None:
    if not has_words:
        return
    i = coords.get("I", 0.0)  # I/J are always relative to the arc start
    j = coords.get("J", 0.0)
    cx, cy = st.x + i, st.y + j
    r = math.hypot(i, j)
    if r < EPS:
        raise GCodeError(line_no, "arc with zero radius (I and J both zero or missing)")

    if st.distance == "G90":
        ex = coords.get("X", st.x)
        ey = coords.get("Y", st.y)
    else:
        ex = st.x + coords.get("X", 0.0)
        ey = st.y + coords.get("Y", 0.0)

    if "Z" in coords:
        zt = coords["Z"] if st.distance == "G90" else st.z + coords["Z"]
        if abs(zt - st.z) > ARC_ENDPOINT_TOL:
            raise GCodeError(
                line_no, "helical arc (Z change during G2/G3) is not supported"
            )

    start_angle = math.atan2(st.y - cy, st.x - cx)
    if math.hypot(ex - st.x, ey - st.y) <= EPS:
        # same start and end point -> full circle
        sweep = math.tau if st.motion == "G3" else -math.tau
        ex, ey = st.x, st.y
    else:
        r_end = math.hypot(ex - cx, ey - cy)
        if abs(r_end - r) > ARC_ENDPOINT_TOL:
            raise GCodeError(
                line_no,
                f"arc end point not on circle (start radius {r:.6f} mm, "
                f"end radius {r_end:.6f} mm)",
            )
        end_angle = math.atan2(ey - cy, ex - cx)
        if st.motion == "G3":
            sweep = (end_angle - start_angle) % math.tau
        else:
            sweep = -((start_angle - end_angle) % math.tau)
        if abs(sweep) < EPS:
            sweep = math.tau if st.motion == "G3" else -math.tau

    arc = Arc(cx, cy, r, start_angle, sweep, st.x, st.y, ex, ey)
    moves.append(Move(line_no, "arc", st.x, st.y, st.z, ex, ey, st.z, arc))
    st.x, st.y = ex, ey
