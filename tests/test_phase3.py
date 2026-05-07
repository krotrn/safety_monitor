import json
from datetime import UTC, datetime, timedelta

import numpy as np

from core.data_store import (
    AlertRecord,
    DataStore,
    FRAMES_TABLE,
    IncidentRecord,
    NearMissRecord,
    RetentionManager,
    SnapshotStore,
)


def test_save_and_get_incident(tmp_path) -> None:
    store = DataStore(":memory:", str(tmp_path))
    record = IncidentRecord(
        source_id="cam_01",
        severity_score=72.5,
        event_type="PersonOnGround",
        triggered_rules=json.dumps(["PersonOnGround"]),
        snapshot_path="2026-05-07/frame.jpg",
    )
    incident_id = store.save_incident(record)
    incidents = store.get_incidents()
    assert incident_id
    assert len(incidents) == 1
    assert incidents[0].id == incident_id


def test_save_near_miss_and_heatmap(tmp_path) -> None:
    store = DataStore(":memory:", str(tmp_path))
    record = NearMissRecord(
        source_id="cam_01",
        track_id_a="1",
        track_id_b="2",
        class_label_a="person",
        class_label_b="car",
        min_distance_px=12.3,
        estimated_ttc_seconds=1.5,
        location_x=0.25,
        location_y=0.75,
        resolved=True,
    )
    near_miss_id = store.save_near_miss(record)
    near_misses = store.get_near_misses()
    heatmap = store.get_heatmap_data()
    assert near_miss_id
    assert len(near_misses) == 1
    assert heatmap == [(0.25, 0.75)]


def test_alert_acknowledge_and_false_positive(tmp_path) -> None:
    store = DataStore(":memory:", str(tmp_path))
    incident = IncidentRecord(
        source_id="cam_01",
        severity_score=80.0,
        event_type="Test",
        triggered_rules=json.dumps(["Test"]),
        snapshot_path=None,
    )
    incident_id = store.save_incident(incident)
    alert = AlertRecord(
        severity_result_id=incident_id,
        source_id="cam_01",
        channels_triggered=json.dumps(["telegram"]),
    )
    alert_id = store.save_alert(alert)

    store.acknowledge_alert(alert_id)
    store.mark_false_positive(alert_id)

    with store.Session() as session:
        refreshed = session.query(AlertRecord).filter(AlertRecord.id == alert_id).one()
        assert refreshed.acknowledged is True
        assert refreshed.false_positive is True
        assert refreshed.acknowledged_at is not None


def test_snapshot_store_save(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    path = store.save("frame-1", frame)
    assert not path.startswith("/")
    assert (tmp_path / path).exists()


def test_retention_manager_prunes_old_frames(tmp_path) -> None:
    store = DataStore(":memory:", str(tmp_path))
    now = datetime.now(UTC).replace(tzinfo=None)
    old_ts = now - timedelta(hours=25)
    new_ts = now - timedelta(hours=1)

    with store.Session() as session:
        session.execute(
            FRAMES_TABLE.insert().values(
                id="old-frame",
                timestamp=old_ts,
                source_id="cam_01",
                detection_count=1,
            )
        )
        session.execute(
            FRAMES_TABLE.insert().values(
                id="new-frame",
                timestamp=new_ts,
                source_id="cam_01",
                detection_count=2,
            )
        )
        session.commit()

    manager = RetentionManager(store, max_frame_age_hours=24)
    manager.run()

    with store.Session() as session:
        rows = session.execute(FRAMES_TABLE.select()).all()
        ids = {row.id for row in rows}
        assert "old-frame" not in ids
        assert "new-frame" in ids
