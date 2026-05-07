from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class IncidentRecord(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC))
    source_id = Column(String, nullable=False)
    severity_score = Column(Float, nullable=False)
    event_type = Column(String, nullable=False)
    triggered_rules = Column(Text, nullable=False)
    snapshot_path = Column(Text, nullable=True)
    acknowledged = Column(Boolean, default=False)
    false_positive = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime, nullable=True)


class NearMissRecord(Base):
    __tablename__ = "near_misses"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC), index=True)
    source_id = Column(String, nullable=False)
    track_id_a = Column(String, nullable=False)
    track_id_b = Column(String, nullable=False)
    class_label_a = Column(String, nullable=False)
    class_label_b = Column(String, nullable=False)
    min_distance_px = Column(Float, nullable=False)
    estimated_ttc_seconds = Column(Float, nullable=True)
    location_x = Column(Float, nullable=False)
    location_y = Column(Float, nullable=False)
    resolved = Column(Boolean, default=True)


class AlertRecord(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    severity_result_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC))
    source_id = Column(String, nullable=False)
    channels_triggered = Column(Text, nullable=False)
    acknowledged = Column(Boolean, default=False)
    false_positive = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime, nullable=True)


FRAMES_TABLE = Table(
    "frames",
    Base.metadata,
    Column("id", String, primary_key=True),
    Column("timestamp", DateTime, nullable=False),
    Column("source_id", String, nullable=False),
    Column("detection_count", Integer, nullable=False),
)


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, frame_id: str, frame: np.ndarray) -> str:
        try:
            date_dir = self.root / datetime.now(UTC).strftime("%Y-%m-%d")
            date_dir.mkdir(parents=True, exist_ok=True)
            path = date_dir / f"{frame_id}.jpg"
            ok = cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                raise RuntimeError("cv2.imwrite returned False")
            return str(path.relative_to(self.root))
        except Exception as exc:
            raise RuntimeError(f"Failed to save snapshot {frame_id}: {exc}") from exc


class DataStore:
    def __init__(self, db_path: str, snapshot_root: str) -> None:
        try:
            db = Path(db_path)
            db.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(self.engine)
            self.Session = sessionmaker(bind=self.engine)
            self.snapshot_root = Path(snapshot_root)
            self.snapshot_root.mkdir(parents=True, exist_ok=True)
            self.snapshot_store = SnapshotStore(self.snapshot_root)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize DataStore: {exc}") from exc

    def save_incident(self, record: IncidentRecord) -> str:
        try:
            with self.Session() as session:
                session.add(record)
                session.commit()
                session.refresh(record)
                return record.id
        except Exception as exc:
            raise RuntimeError(f"Failed to save incident: {exc}") from exc

    def save_near_miss(self, record: NearMissRecord) -> str:
        try:
            with self.Session() as session:
                session.add(record)
                session.commit()
                session.refresh(record)
                return record.id
        except Exception as exc:
            raise RuntimeError(f"Failed to save near miss: {exc}") from exc

    def save_alert(self, record: AlertRecord) -> str:
        try:
            with self.Session() as session:
                session.add(record)
                session.commit()
                session.refresh(record)
                return record.id
        except Exception as exc:
            raise RuntimeError(f"Failed to save alert: {exc}") from exc

    def get_incidents(self, limit: int = 50, offset: int = 0) -> List[IncidentRecord]:
        try:
            with self.Session() as session:
                return (
                    session.query(IncidentRecord)
                    .order_by(IncidentRecord.timestamp.desc())
                    .offset(offset)
                    .limit(limit)
                    .all()
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to get incidents: {exc}") from exc

    def get_near_misses(self, limit: int = 200) -> List[NearMissRecord]:
        try:
            with self.Session() as session:
                return (
                    session.query(NearMissRecord)
                    .order_by(NearMissRecord.timestamp.desc())
                    .limit(limit)
                    .all()
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to get near misses: {exc}") from exc

    def get_heatmap_data(self) -> List[Tuple[float, float]]:
        try:
            with self.Session() as session:
                rows = session.execute(
                    select(NearMissRecord.location_x, NearMissRecord.location_y)
                ).all()
                return [(float(x), float(y)) for x, y in rows]
        except Exception as exc:
            raise RuntimeError(f"Failed to get heatmap data: {exc}") from exc

    def get_stats(self) -> Dict[str, int]:
        try:
            with self.Session() as session:
                incidents = session.query(func.count(IncidentRecord.id)).scalar() or 0
                near_misses = session.query(func.count(NearMissRecord.id)).scalar() or 0
                alerts = session.query(func.count(AlertRecord.id)).scalar() or 0
                return {
                    "incidents": int(incidents),
                    "near_misses": int(near_misses),
                    "alerts": int(alerts),
                }
        except Exception as exc:
            raise RuntimeError(f"Failed to get stats: {exc}") from exc

    def acknowledge_alert(self, alert_id: str) -> None:
        try:
            with self.Session() as session:
                record = session.query(AlertRecord).filter(AlertRecord.id == alert_id).one_or_none()
                if record is None:
                    logger.warning("Alert %s not found for acknowledge", alert_id)
                    return
                record.acknowledged = True
                record.acknowledged_at = datetime.now(UTC)
                session.commit()
        except Exception as exc:
            raise RuntimeError(f"Failed to acknowledge alert {alert_id}: {exc}") from exc

    def mark_false_positive(self, alert_id: str) -> None:
        try:
            with self.Session() as session:
                record = session.query(AlertRecord).filter(AlertRecord.id == alert_id).one_or_none()
                if record is None:
                    logger.warning("Alert %s not found for false positive", alert_id)
                    return
                record.false_positive = True
                record.acknowledged = True
                record.acknowledged_at = datetime.now(UTC)
                session.commit()
        except Exception as exc:
            raise RuntimeError(f"Failed to mark false positive for {alert_id}: {exc}") from exc

    def acknowledge_incident(self, incident_id: str) -> None:
        try:
            with self.Session() as session:
                record = (
                    session.query(IncidentRecord)
                    .filter(IncidentRecord.id == incident_id)
                    .one_or_none()
                )
                if record is None:
                    logger.warning("Incident %s not found for acknowledge", incident_id)
                    return
                record.acknowledged = True
                record.acknowledged_at = datetime.now(UTC)
                session.commit()
        except Exception as exc:
            raise RuntimeError(f"Failed to acknowledge incident {incident_id}: {exc}") from exc

    def mark_incident_false_positive(self, incident_id: str) -> None:
        try:
            with self.Session() as session:
                record = (
                    session.query(IncidentRecord)
                    .filter(IncidentRecord.id == incident_id)
                    .one_or_none()
                )
                if record is None:
                    logger.warning("Incident %s not found for false positive", incident_id)
                    return
                record.false_positive = True
                record.acknowledged = True
                record.acknowledged_at = datetime.now(UTC)
                session.commit()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to mark incident false positive for {incident_id}: {exc}"
            ) from exc

    def mark_near_miss_unresolved(self, event_id: str) -> None:
        try:
            with self.Session() as session:
                record = (
                    session.query(NearMissRecord)
                    .filter(NearMissRecord.id == event_id)
                    .one_or_none()
                )
                if record is None:
                    return
                record.resolved = False
                session.commit()
        except Exception as exc:
            logger.error("Failed to mark near miss unresolved: %s", exc)


class RetentionManager:
    def __init__(self, store: DataStore, max_frame_age_hours: int = 24) -> None:
        self.store = store
        self.max_frame_age_hours = int(max_frame_age_hours)

    def run(self) -> None:
        try:
            cutoff = datetime.now(UTC) - timedelta(hours=self.max_frame_age_hours)
            with self.store.Session() as session:
                session.execute(delete(FRAMES_TABLE).where(FRAMES_TABLE.c.timestamp < cutoff))
                session.commit()
        except Exception as exc:
            raise RuntimeError(f"Retention cleanup failed: {exc}") from exc
