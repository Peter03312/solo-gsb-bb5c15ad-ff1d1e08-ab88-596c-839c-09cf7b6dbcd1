"""Database setup and ORM models (PostgreSQL; SQLite works for local tests)."""

from __future__ import annotations

import os
import time

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://cnc:cnc@localhost:5432/cnc")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=True)
    current_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ZoneVersion(Base):
    """Immutable geometry snapshot; rows are never updated or deleted."""

    __tablename__ = "zone_versions"

    zone_id = Column(Integer, ForeignKey("zones.id"), primary_key=True)
    version = Column(Integer, primary_key=True)
    polygon = Column(JSON, nullable=False)  # [[x, y], ...] in mm
    z_min = Column(Float, nullable=False)
    z_max = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Report(Base):
    """Immutable review report; never changes after creation."""

    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    zones_used = Column(JSON, nullable=False)  # [{"zone_id": ..., "version": ...}, ...]
    input_summary = Column(JSON, nullable=False)
    collision = Column(Boolean, nullable=False)
    collision_line = Column(Integer, nullable=True)
    collision_zone_id = Column(Integer, nullable=True)


def init_db(retries: int = 30, delay: float = 1.0) -> None:
    """Create tables, waiting for the database to become available."""
    for attempt in range(retries):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
