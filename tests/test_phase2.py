import time
import uuid
from datetime import UTC, datetime

import numpy as np

from core.models import Detection, DetectionResult
from core.object_tracker import ObjectTracker


def build_detection(track_id: int, bbox, label: str = "person", confidence: float = 0.9) -> Detection:
    detection = Detection(
        object_id=str(uuid.uuid4()),
        class_label=label,
        confidence=confidence,
        bbox=bbox,
        bbox_norm=[0.0, 0.0, 1.0, 1.0],
    )
    setattr(detection, "track_id", track_id)
    return detection


def build_result(detections) -> DetectionResult:
    return DetectionResult(
        frame_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC).replace(microsecond=0).isoformat(),
        source_id="cam_01",
        detections=detections,
    )


def make_tracker(stale_timeout: float | None = None) -> ObjectTracker:
    config = {
        "target_fps": 15,
        "history_window_seconds": 5,
        "stationary_velocity_threshold": 5.0,
    }
    if stale_timeout is not None:
        config["stale_track_timeout_seconds"] = stale_timeout
    return ObjectTracker(config)


def test_track_id_persists_across_frames() -> None:
    tracker = make_tracker()
    raw_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    track_id = 4
    for _ in range(50):
        detection = build_detection(track_id, [10, 10, 20, 20])
        result = tracker.update(build_result([detection]), raw_frame)
        assert result.detections[0].track_id == track_id


def test_positions_and_velocities_accumulate() -> None:
    tracker = make_tracker()
    raw_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detection = build_detection(1, [10, 10, 20, 20])
    tracker.update(build_result([detection]), raw_frame)
    detection = build_detection(1, [12, 10, 22, 20])
    result = tracker.update(build_result([detection]), raw_frame)
    tracked = result.detections[0]
    assert len(tracked.positions) == 2
    assert len(tracked.velocities) == 1
    assert tracked.velocities[0] > 0


def test_stationary_detected_and_duration() -> None:
    tracker = make_tracker()
    raw_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    for _ in range(12):
        detection = build_detection(2, [10, 10, 20, 20])
        result = tracker.update(build_result([detection]), raw_frame)
    tracked = result.detections[0]
    assert tracked.is_stationary is True
    assert tracked.stationary_duration > 0.0


def test_untracked_detection_skipped() -> None:
    tracker = make_tracker()
    raw_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detection = build_detection(-1, [10, 10, 20, 20])
    result = tracker.update(build_result([detection]), raw_frame)
    assert result.detections == []


def test_stale_track_purged() -> None:
    tracker = make_tracker(stale_timeout=0.01)
    raw_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detection = build_detection(3, [10, 10, 20, 20])
    tracker.update(build_result([detection]), raw_frame)
    time.sleep(0.02)
    tracker.update(build_result([]), raw_frame)
    assert 3 not in tracker._tracks


def test_empty_detection_result_returns_empty_tracked_frame() -> None:
    tracker = make_tracker()
    raw_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = tracker.update(build_result([]), raw_frame)
    assert result.detections == []
    assert result.raw_frame is raw_frame
