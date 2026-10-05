"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, FiniteFloat, model_validator


class ZoneGeometry(BaseModel):
    polygon: list[tuple[FiniteFloat, FiniteFloat]] = Field(
        min_length=3, description="2D polygon vertices in mm, implicitly closed"
    )
    z_min: FiniteFloat = Field(description="lower bound of the forbidden Z range (mm)")
    z_max: FiniteFloat = Field(description="upper bound of the forbidden Z range (mm)")

    @model_validator(mode="after")
    def _check_z_range(self):
        if self.z_min > self.z_max:
            raise ValueError("z_min must be <= z_max")
        return self


class ZoneCreate(ZoneGeometry):
    name: Optional[str] = Field(default=None, max_length=200)


class ZoneOut(BaseModel):
    zone_id: int
    version: int
    current_version: int
    name: Optional[str]
    polygon: list[list[float]]
    z_min: float
    z_max: float


class ZoneRef(BaseModel):
    zone_id: int
    version: int = Field(ge=1)


class Position(BaseModel):
    x: FiniteFloat
    y: FiniteFloat
    z: FiniteFloat


class ReviewRequest(BaseModel):
    zones: list[ZoneRef] = Field(
        min_length=1, description="forbidden zones pinned to exact versions"
    )
    initial_position: Position = Field(description="initial tool tip position in mm")
    tool_radius: FiniteFloat = Field(ge=0.0, description="tool radius in mm")
    gcode: str = Field(min_length=1, max_length=2_000_000)


class ReportOut(BaseModel):
    report_id: int
    created_at: Optional[datetime]
    zones_used: list[dict]
    input_summary: dict
    collision: bool
    collision_line: Optional[int]
    collision_zone_id: Optional[int]


class ReportListItem(BaseModel):
    report_id: int
    created_at: Optional[datetime]
    collision: bool
    collision_line: Optional[int]
    collision_zone_id: Optional[int]
