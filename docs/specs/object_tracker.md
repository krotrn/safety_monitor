# Spec — object_tracker.py (Layer 3)

**Module:** `core/object_tracker.py`  
**Layer:** 3 — Tracking & Motion  
**Input:** `DetectionResult`  
**Output:** `TrackedFrame`  
**Depends on:** `core/models.py`  
**Used by:** `severity_engine.py`, `nearmiss_tracker.py`

---

## Responsibility

Take raw detections with `track_id` (already assigned by `model.track()` in Layer 2)
and enrich them with motion history: position trajectory, velocity, stationary state.

This module does **not** do the tracking itself — `model.track(persist=True)` in
`InferenceEngine` handles ID assignment. This module maintains the rolling state
that makes detection history available to downstream scorers.

---

## Classes

### `TrackState`

Internal per-object rolling state. Not exposed outside this module.

```python
from collections import deque
from dataclasses import dataclass, field
import time

@dataclass
class TrackState:
    track_id: int
    class_label: str
    positions: deque  # deque of (cx, cy) tuples, maxlen=75 (~5s at 15fps)
    velocities: deque # deque of float px/frame distances, maxlen=75
    last_seen: float  # time.time() of last detection

    @property
    def is_stationary(self) -> bool:
        if len(self.velocities) < 10:
            return False
        return (sum(list(self.velocities)[-10:]) / 10) < 5.0

    @property
    def stationary_duration(self) -> float:
        """Seconds object has been continuously below velocity threshold."""
        if len(self.velocities) < 10:
            return 0.0
        count = 0
        for v in reversed(self.velocities):
            if v < 5.0:
                count += 1
            else:
                break
        return count / 15.0  # target_fps from config
```

**Deque sizing:**
- `maxlen=75` at 15 FPS = 5 second window
- When target_fps changes in config, `maxlen = target_fps * window_seconds`
- Window duration configured via `tracker.history_window_seconds` (default: 5)

---

### `ObjectTracker`

```python
class ObjectTracker:
    def __init__(self, config: dict):
        """
        config keys:
          target_fps: int              # from camera config
          history_window_seconds: int  # default 5
          stationary_velocity_threshold: float  # default 5.0 px/frame
          stale_track_timeout_seconds: float    # default 2.0
        """
        ...

    def update(self, detection_result: DetectionResult, raw_frame: np.ndarray) -> TrackedFrame:
        """
        Enrich detections with motion history.
        Returns TrackedFrame with all valid (track_id >= 0) detections.
        """
        ...

    def _get_or_create_state(self, track_id: int, class_label: str) -> TrackState:
        ...

    def _compute_center(self, bbox: List[int]) -> Tuple[float, float]:
        ...

    def _purge_stale_tracks(self) -> None:
        """Remove tracks not seen in stale_track_timeout_seconds."""
        ...
```

#### `update()` Internal Flow

```
1. _purge_stale_tracks()
   — remove any TrackState not updated in > stale_track_timeout_seconds
   — prevents memory leak for objects that leave frame

2. For each detection in detection_result.detections:
   a. Skip if track_id == -1 (untracked, drop silently)
   b. state = _get_or_create_state(track_id, class_label)
   c. center = _compute_center(detection.bbox)
   d. if state.positions is not empty:
        velocity = euclidean_distance(center, state.positions[-1])
        state.velocities.append(velocity)
   e. state.positions.append(center)
   f. state.last_seen = time.time()
   g. Build TrackedDetection from Detection + state fields

3. Return TrackedFrame with all built TrackedDetections + raw_frame
```

#### Building `TrackedDetection`

```python
TrackedDetection(
    # All Detection fields copied directly
    object_id    = detection.object_id,
    class_label  = detection.class_label,
    confidence   = detection.confidence,
    bbox         = detection.bbox,
    bbox_norm    = detection.bbox_norm,

    # Tracker additions
    track_id              = detection.track_id,
    center                = center,
    positions             = list(state.positions),      # snapshot of deque
    velocities            = list(state.velocities),     # snapshot of deque
    is_stationary         = state.is_stationary,
    stationary_duration   = state.stationary_duration,
)
```

---

## Internal State

```python
self._tracks: Dict[int, TrackState] = {}
```

- Key: `track_id` (int)
- Value: `TrackState`
- Grows as new objects appear, shrinks as stale tracks are purged
- Not persisted — state is lost on restart (intentional for minor project)

---

## Config Keys

```yaml
tracker:
  history_window_seconds: 5
  stationary_velocity_threshold: 5.0   # px/frame below which object is "stationary"
  stale_track_timeout_seconds: 2.0     # seconds before unseen track is purged
```

Also reads `camera.target_fps` to compute deque maxlen.

---

## Velocity Calculation

```
velocity = sqrt((cx2 - cx1)^2 + (cy2 - cy1)^2)
```

Where `(cx1, cy1)` is the previous center and `(cx2, cy2)` is the current center, both in pixels.

This is frame-to-frame pixel distance. It is **not** normalized by time — it assumes
constant FPS. If FPS drops significantly, velocity readings become unreliable.
Acceptable for minor project. Major project should use timestamp delta instead.

---

## Stale Track Purging

Tracks are purged when `time.time() - state.last_seen > stale_track_timeout_seconds`.

Purging runs at the **start** of every `update()` call.

This prevents:
- Memory growing unbounded in long sessions
- Track IDs from re-appearing objects getting stale history from previous appearances

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| `track_id == -1` | Detection skipped silently — not added to TrackedFrame |
| Single detection missing bbox | Log WARNING, skip that detection |
| All detections have `track_id == -1` | Return `TrackedFrame` with `detections=[]` |
| `raw_frame` is None | Log ERROR, raise `ValueError` — frame is required for snapshot |

---

## Scalability Hook

`TrackState` is keyed by `track_id` integer. When moving to multi-camera in the major project,
key becomes `(source_id, track_id)` tuple — same track_id can exist on two cameras independently.
Only `_get_or_create_state()` and `_purge_stale_tracks()` need updating.

---

## Tests — `tests/test_object_tracker.py`

| Test | Assertion |
|------|-----------|
| `test_track_id_persists` | Same `track_id` across 50 consecutive frames for same object |
| `test_positions_accumulate` | `positions` list grows per frame up to window max |
| `test_velocity_computed` | `velocities` non-empty after second frame for same track |
| `test_stationary_detected` | `is_stationary=True` after 10 frames with no movement |
| `test_stationary_duration` | `stationary_duration` increases correctly per frame |
| `test_stale_track_purged` | Track removed from `_tracks` after timeout |
| `test_untracked_detection_skipped` | `track_id=-1` detections not in `TrackedFrame.detections` |
| `test_empty_detection_result` | Empty `DetectionResult` returns `TrackedFrame` with `detections=[]` |
| `test_tracked_frame_has_raw_frame` | `TrackedFrame.raw_frame` is the same ndarray passed in |

---

## Done When

- Same person walking across `tests/sample.mp4` holds the same `track_id` for ≥ 50 frames
- `positions` list length grows up to 75 entries
- `is_stationary` flips to `True` when test object stops moving for 10+ frames
- Stale tracks cleaned from `_tracks` dict after `stale_track_timeout_seconds`