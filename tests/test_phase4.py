import uuid
from datetime import UTC, datetime

import numpy as np

from core.models import TrackedDetection, TrackedFrame
from core.severity_engine import ActionTierMapper, SeverityEngine


BASE_PROFILE = {
    "person_on_ground_threshold_seconds": 4,
    "vehicle_sudden_stop_decel_threshold": 0.6,
    "person_vehicle_proximity_px": 80,
    "nighttime_start_hour": 21,
    "nighttime_end_hour": 5,
    "person_on_ground_aspect_ratio_threshold": 1.5,
}


def make_tracked_detection(
    track_id: int,
    class_label: str,
    bbox,
    velocities=None,
    stationary_duration: float = 0.0,
) -> TrackedDetection:
    if velocities is None:
        velocities = []
    center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    positions = [center] * (len(velocities) + 1)
    return TrackedDetection(
        object_id=str(uuid.uuid4()),
        class_label=class_label,
        confidence=0.9,
        bbox=bbox,
        bbox_norm=[0.0, 0.0, 1.0, 1.0],
        track_id=track_id,
        center=center,
        positions=positions,
        velocities=velocities,
        is_stationary=stationary_duration > 0.0,
        stationary_duration=stationary_duration,
    )


def make_tracked_frame(detections, timestamp: str) -> TrackedFrame:
    return TrackedFrame(
        frame_id=str(uuid.uuid4()),
        timestamp=timestamp,
        source_id="cam_01",
        raw_frame=np.zeros((480, 640, 3), dtype=np.uint8),
        detections=detections,
    )


def test_empty_frame_scores_zero() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    frame = make_tracked_frame([], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert result.severity_score == 0.0
    assert result.action_tier == "silent"
    assert result.event_type == "none"


def test_person_on_ground_scores_50() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    detection = make_tracked_detection(1, "person", [10, 10, 210, 60])
    frame = make_tracked_frame([detection], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert result.severity_score >= 50
    assert "PersonOnGround" in result.triggered_rules


def test_person_stationary_adds_20() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    detection = make_tracked_detection(
        2,
        "person",
        [10, 10, 60, 110],
        stationary_duration=5.0,
    )
    frame = make_tracked_frame([detection], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert "PersonStationary" in result.triggered_rules
    assert result.severity_score >= 20


def test_combined_score_capped_at_100() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    person = make_tracked_detection(1, "person", [10, 10, 210, 60], stationary_duration=5.0)
    car_a = make_tracked_detection(2, "car", [50, 50, 150, 150])
    car_b = make_tracked_detection(3, "truck", [80, 80, 160, 160])
    frame = make_tracked_frame([person, car_a, car_b], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert result.severity_score == 100.0


def test_vehicle_collision_scores_60() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    car_a = make_tracked_detection(2, "car", [10, 10, 100, 100])
    car_b = make_tracked_detection(3, "truck", [50, 50, 120, 120])
    frame = make_tracked_frame([car_a, car_b], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert "VehicleCollision" in result.triggered_rules
    assert result.severity_score >= 60


def test_sudden_stop_scores_30() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    velocities = [10, 10, 10, 10, 10, 3]
    car = make_tracked_detection(4, "car", [10, 10, 100, 100], velocities=velocities)
    frame = make_tracked_frame([car], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert "SuddenStop" in result.triggered_rules
    assert result.severity_score >= 30


def test_person_vehicle_proximity_scores_25() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    person = make_tracked_detection(1, "person", [10, 10, 30, 30])
    car = make_tracked_detection(2, "car", [20, 20, 40, 40])
    frame = make_tracked_frame([person, car], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert "PersonVehicleProximity" in result.triggered_rules
    assert result.severity_score >= 25


def test_nighttime_modifier() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    person = make_tracked_detection(1, "person", [10, 10, 30, 60])
    frame = make_tracked_frame([person], "2026-05-06T22:00:00")
    result = engine.score(frame)
    assert "Nighttime" in result.triggered_rules


def test_tier_mapping() -> None:
    assert ActionTierMapper.map(0) == "silent"
    assert ActionTierMapper.map(30) == "silent"
    assert ActionTierMapper.map(31) == "flag"
    assert ActionTierMapper.map(60) == "flag"
    assert ActionTierMapper.map(61) == "alert"


def test_event_type_is_first_triggered_rule() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    person = make_tracked_detection(1, "person", [10, 10, 210, 60], stationary_duration=5.0)
    frame = make_tracked_frame([person], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert result.event_type == "PersonOnGround"


def test_event_type_none_when_no_rules() -> None:
    engine = SeverityEngine(BASE_PROFILE)
    person = make_tracked_detection(1, "person", [10, 10, 30, 80])
    frame = make_tracked_frame([person], "2026-05-06T12:00:00")
    result = engine.score(frame)
    assert result.event_type == "none"
    assert result.severity_score == 0.0
