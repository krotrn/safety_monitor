import pytest
import numpy as np
from unittest.mock import Mock

from core.models import TrackedDetection, TrackedFrame
from core.nearmiss_tracker import NearMissTracker, TrajectoryAnalyzer, NearMissBuffer, HeatmapAccumulator

@pytest.fixture
def profile():
    return {
        "near_miss_proximity_px": 80.0,
        "near_miss_ttc_threshold_seconds": 1.5,
        "near_miss_min_frames": 2,
    }

@pytest.fixture
def store():
    mock_store = Mock()
    mock_store.save_near_miss = Mock()
    return mock_store

def create_tracked_detection(track_id, cx, cy, label="person"):
    return TrackedDetection(
        object_id=f"obj_{track_id}",
        class_label=label,
        confidence=0.9,
        bbox=[int(cx-10), int(cy-10), int(cx+10), int(cy+10)],
        bbox_norm=[0.1, 0.1, 0.2, 0.2],
        track_id=track_id,
        center=(cx, cy),
        positions=[(cx, cy)] * 5,
        velocities=[0.0] * 4,
        is_stationary=True,
        stationary_duration=1.0,
    )

def test_no_event_single_object(profile, store):
    tracker = NearMissTracker(profile, store)
    det1 = create_tracked_detection(1, 100.0, 100.0)
    frame = TrackedFrame(
        frame_id="f1",
        timestamp="2026-05-06T12:00:00Z",
        source_id="cam_01",
        raw_frame=np.zeros((480, 640, 3), dtype=np.uint8),
        detections=[det1],
    )
    events = tracker.process(frame)
    assert len(events) == 0

def test_no_event_distant_objects(profile, store):
    tracker = NearMissTracker(profile, store)
    det1 = create_tracked_detection(1, 100.0, 100.0)
    det2 = create_tracked_detection(2, 500.0, 500.0)
    frame = TrackedFrame(
        frame_id="f1",
        timestamp="2026-05-06T12:00:00Z",
        source_id="cam_01",
        raw_frame=np.zeros((480, 640, 3), dtype=np.uint8),
        detections=[det1, det2],
    )
    events = tracker.process(frame)
    assert len(events) == 0

def test_event_emitted_at_min_frames(profile, store):
    tracker = NearMissTracker(profile, store)
    det1 = create_tracked_detection(1, 100.0, 100.0)
    det2 = create_tracked_detection(2, 110.0, 100.0) # distance 10 < 80
    
    frame1 = TrackedFrame("f1", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2])
    events1 = tracker.process(frame1)
    assert len(events1) == 0 # min_frames is 2
    
    frame2 = TrackedFrame("f2", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2])
    events2 = tracker.process(frame2)
    assert len(events2) == 1
    assert events2[0].track_id_a in (1, 2)

def test_not_emitted_before_min_frames(profile, store):
    tracker = NearMissTracker(profile, store)
    det1 = create_tracked_detection(1, 100.0, 100.0)
    det2 = create_tracked_detection(2, 110.0, 100.0)
    
    frame = TrackedFrame("f1", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2])
    events = tracker.process(frame)
    assert len(events) == 0

def test_heatmap_records_location(profile, store):
    tracker = NearMissTracker(profile, store)
    det1 = create_tracked_detection(1, 320.0, 240.0)
    det2 = create_tracked_detection(2, 330.0, 240.0)
    
    frame = TrackedFrame("f1", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2])
    tracker.process(frame)
    tracker.process(frame)
    
    pts = tracker.get_heatmap_points()
    assert len(pts) > 0

def test_heatmap_grid_cell_correct(profile, store):
    tracker = NearMissTracker(profile, store)
    # Put near miss at (0, 0), so mid is (0, 0)
    det1 = create_tracked_detection(1, 0.0, 0.0)
    det2 = create_tracked_detection(2, 10.0, 0.0)
    frame = TrackedFrame("f1", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2])
    tracker.process(frame)
    tracker.process(frame)
    
    pts = tracker.get_heatmap_points()
    # It should be in top left cell
    assert len(pts) == 1
    assert pts[0]["x"] == 0.5 / 20.0
    assert pts[0]["y"] == 0.5 / 20.0

def test_buffer_cleaned_when_separated(profile, store):
    tracker = NearMissTracker(profile, store)
    det1 = create_tracked_detection(1, 100.0, 100.0)
    det2 = create_tracked_detection(2, 110.0, 100.0)
    frame1 = TrackedFrame("f1", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2])
    tracker.process(frame1) # Count = 1
    
    # Now separate them
    det2_far = create_tracked_detection(2, 500.0, 500.0)
    frame2 = TrackedFrame("f2", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2_far])
    tracker.process(frame2) # Count should reset
    
    # Bring back together
    frame3 = TrackedFrame("f3", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2])
    events = tracker.process(frame3)
    assert len(events) == 0 # Count is 1 again, not 2

def test_ttc_negative_when_moving_apart(profile, store):
    analyzer = TrajectoryAnalyzer(profile)
    det1 = create_tracked_detection(1, 100.0, 100.0)
    det2 = create_tracked_detection(2, 200.0, 100.0)
    
    # det1 moving left
    det1.positions = [(110, 100), (105, 100), (100, 100)]
    # det2 moving right
    det2.positions = [(190, 100), (195, 100), (200, 100)]
    
    ttc = analyzer._estimate_ttc(det1, det2)
    assert ttc == -1.0

def test_db_save_called(profile, store):
    tracker = NearMissTracker(profile, store)
    det1 = create_tracked_detection(1, 100.0, 100.0)
    det2 = create_tracked_detection(2, 110.0, 100.0)
    frame = TrackedFrame("f1", "ts", "cam", np.zeros((480, 640, 3)), [det1, det2])
    tracker.process(frame)
    tracker.process(frame)
    
    store.save_near_miss.assert_called_once()
