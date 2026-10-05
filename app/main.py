"""FastAPI application: forbidden-zone registry + toolpath review service."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from .db import Report, SessionLocal, Zone, ZoneVersion, get_db, init_db
from .gcode import GCodeError, parse_program
from .geometry import GeometryError, validate_polygon
from .review import find_first_collision
from .schemas import (
    ReportListItem,
    ReportOut,
    ReviewRequest,
    ZoneCreate,
    ZoneGeometry,
    ZoneOut,
)

@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="CNC Toolpath Forbidden-Zone Review Service",
    version="1.0.0",
    description=(
        "Registers millimetre-based 2D polygon forbidden zones with closed Z "
        "ranges (immutable versions) and reviews G-code toolpaths against them."
    ),
    lifespan=_lifespan,
)


def _get_zone(db: Session, zone_id: int) -> Zone:
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"zone {zone_id} not found")
    return zone


def _zone_out(zone: Zone, zv: ZoneVersion) -> ZoneOut:
    return ZoneOut(
        zone_id=zone.id,
        version=zv.version,
        current_version=zone.current_version,
        name=zone.name,
        polygon=[[float(x), float(y)] for x, y in zv.polygon],
        z_min=zv.z_min,
        z_max=zv.z_max,
    )


def _validate_geometry(body: ZoneGeometry) -> list[tuple[float, float]]:
    polygon = [(float(x), float(y)) for x, y in body.polygon]
    try:
        validate_polygon(polygon)
    except GeometryError as exc:
        raise HTTPException(status_code=422, detail=f"invalid polygon: {exc}")
    return polygon


# --------------------------------------------------------------------- zones

@app.post("/zones", status_code=201, response_model=ZoneOut)
def create_zone(body: ZoneCreate, db: Session = Depends(get_db)):
    """Register a new forbidden zone (version 1)."""
    polygon = _validate_geometry(body)
    zone = Zone(name=body.name, current_version=1)
    db.add(zone)
    db.flush()
    zv = ZoneVersion(
        zone_id=zone.id, version=1,
        polygon=[[x, y] for x, y in polygon],
        z_min=body.z_min, z_max=body.z_max,
    )
    db.add(zv)
    db.commit()
    db.refresh(zone)
    return _zone_out(zone, zv)


@app.put("/zones/{zone_id}", status_code=201, response_model=ZoneOut)
def update_zone(zone_id: int, body: ZoneGeometry, db: Session = Depends(get_db)):
    """Modify a zone: creates a new immutable version, old versions stay usable."""
    polygon = _validate_geometry(body)
    zone = db.get(Zone, zone_id, with_for_update=True)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"zone {zone_id} not found")
    new_version = zone.current_version + 1
    zv = ZoneVersion(
        zone_id=zone.id, version=new_version,
        polygon=[[x, y] for x, y in polygon],
        z_min=body.z_min, z_max=body.z_max,
    )
    db.add(zv)
    zone.current_version = new_version
    db.commit()
    db.refresh(zone)
    return _zone_out(zone, zv)


@app.get("/zones/{zone_id}", response_model=ZoneOut)
def get_zone(zone_id: int, db: Session = Depends(get_db)):
    """Get the current version of a zone."""
    zone = _get_zone(db, zone_id)
    zv = db.get(ZoneVersion, (zone_id, zone.current_version))
    return _zone_out(zone, zv)


@app.get("/zones/{zone_id}/versions", response_model=list[int])
def list_zone_versions(zone_id: int, db: Session = Depends(get_db)):
    _get_zone(db, zone_id)
    rows = (
        db.query(ZoneVersion.version)
        .filter(ZoneVersion.zone_id == zone_id)
        .order_by(ZoneVersion.version)
        .all()
    )
    return [r[0] for r in rows]


@app.get("/zones/{zone_id}/versions/{version}", response_model=ZoneOut)
def get_zone_version(zone_id: int, version: int, db: Session = Depends(get_db)):
    zone = _get_zone(db, zone_id)
    zv = db.get(ZoneVersion, (zone_id, version))
    if zv is None:
        raise HTTPException(
            status_code=404, detail=f"zone {zone_id} version {version} not found"
        )
    return _zone_out(zone, zv)


# ------------------------------------------------------------------- reviews

@app.post("/reviews", status_code=201, response_model=ReportOut)
def create_review(body: ReviewRequest, db: Session = Depends(get_db)):
    """Review a G-code program against the given forbidden-zone versions.

    Illegal input (geometry, radius, arcs, unsupported motion/coordinate
    commands) is rejected with 422 and leaves no report behind.
    """
    zones = []
    for ref in body.zones:
        zv = db.get(ZoneVersion, (ref.zone_id, ref.version))
        if zv is None:
            raise HTTPException(
                status_code=404,
                detail=f"zone {ref.zone_id} version {ref.version} not found",
            )
        polygon = [(float(x), float(y)) for x, y in zv.polygon]
        zones.append((ref.zone_id, polygon, zv.z_min, zv.z_max))
    zones.sort(key=lambda z: z[0])  # deterministic first-collision reporting

    try:
        moves = parse_program(
            body.gcode,
            body.initial_position.x,
            body.initial_position.y,
            body.initial_position.z,
        )
    except GCodeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"line": exc.line_no, "message": exc.message},
        )

    hit = find_first_collision(moves, zones, body.tool_radius)

    report = Report(
        zones_used=[{"zone_id": r.zone_id, "version": r.version} for r in body.zones],
        input_summary={
            "initial_position": {
                "x": body.initial_position.x,
                "y": body.initial_position.y,
                "z": body.initial_position.z,
            },
            "tool_radius": body.tool_radius,
            "gcode_lines": len(body.gcode.splitlines()),
            "gcode_sha256": hashlib.sha256(body.gcode.encode("utf-8")).hexdigest(),
        },
        collision=hit is not None,
        collision_line=hit[0] if hit else None,
        collision_zone_id=hit[1] if hit else None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return _report_out(report)


def _report_out(report: Report) -> ReportOut:
    return ReportOut(
        report_id=report.id,
        created_at=report.created_at,
        zones_used=report.zones_used,
        input_summary=report.input_summary,
        collision=report.collision,
        collision_line=report.collision_line,
        collision_zone_id=report.collision_zone_id,
    )


@app.get("/reports", response_model=list[ReportListItem])
def list_reports(db: Session = Depends(get_db)):
    rows = db.query(Report).order_by(Report.id).all()
    return [
        ReportListItem(
            report_id=r.id,
            created_at=r.created_at,
            collision=r.collision,
            collision_line=r.collision_line,
            collision_zone_id=r.collision_zone_id,
        )
        for r in rows
    ]


@app.get("/reports/{report_id}", response_model=ReportOut)
def get_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"report {report_id} not found")
    return _report_out(report)


@app.get("/health")
def health():
    return {"status": "ok"}
