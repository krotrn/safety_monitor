# Spec — nearmiss_tracker.py (Layer 5)

**Module:** `core/nearmiss_tracker.py`  
**Layer:** 5 — Near-Miss Detection  
**Input:** `TrackedFrame`  
**Output:** `NearMissEvent` (written to `data_store`)  
**Depends on:** `core/models.py`, `core/data_store.py`  
**Used by:** `data_store.py` (writes), `dashboard` (reads heatmap)

---

## Responsibility

Watch object trajectories over a rolling time window.
Flag events where two objects came dangerously close but no confirmed incident occurred.
Build and persist a spatial heatmap of where near-misses cluster.

This is the differentiator feature — it gives value even when no accidents happen.
A security admin can see the heatmap and fix a dangerous zone before an accident occurs.

This module does **not** trigger alerts. Near-misses are logged silently.
If the same event escalates to an incident (severity score ≥ 61 within 2 seconds),
the `NearMissRecord.resolved` flag is set to `False` retroactively.

---

## Classes

### `TrajectoryAnalyzer`

Evaluates proximity and collision risk between all pairs of tracked objects per frame.

```python
from dataclasses import dataclass
from typing import List, Tuple, Optional

class TrajectoryAnalyzer:
    def __init__(self, profile: dict):
        """
        profile keys used:
          near_miss_proximity_px: float
          near_miss_ttc_threshold_seconds: float  (default 1.5)
          near_miss_min_frames: int               (default 2)
        """
        self.proximity_threshold = profile["near_miss_proximity_px"]
        self.ttc_threshold = profile.get("near_miss_ttc_threshold_seconds", 1.5)
        self.min_frames = profile.get("near_miss_min_frames", 2)

    def analyze(self, tracked_frame: TrackedFrame) -> List[NearMissCandidate]:
        """
        For every pair of objects, check:
          1. Are they within proximity_threshold?
          2. OR is their estimated TTC < ttc_threshold?
        Returns list of NearMissCandidates — may be empty.
        """
        ...
```

#### Proximity Check

```python
def _check_proximity(self, a: TrackedDetection, b: TrackedDetection) -> Optional[float]:
    """Return center distance in px if within threshold, else None."""
    cx_a, cy_a = a.center
    cx_b, cy_b = b.center
    dist = ((cx_a - cx_b)**2 + (cy_a - cy_b)**2) ** 0.5
    if dist < self.proximity_threshold:
        return dist
    return None
```

#### Time-to-Collision Estimate

```python
def _estimate_ttc(self, a: TrackedDetection, b: TrackedDetection) -> float:
    """
    Estimate seconds until objects would collide if continuing current velocities.
    Returns -1.0 if objects are moving apart or parallel.

    Method: project velocity vectors, find closest future approach.
    Simplified linear extrapolation — good enough for minor project.
    """
    if len(a.positions) < 2 or len(b.positions) < 2:
        return -1.0

    # Current positions
    ax, ay = a.center
    bx, by = b.center

    # Velocity vectors (last 3 frame average for stability)
    def avg_velocity_vector(det: TrackedDetection) -> Tuple[float, float]:
        positions = det.positions[-4:]
        if len(positions) < 2:
            return (0.0, 0.0)
        dx = positions[-1][0] - positions[0][0]
        dy = positions[-1][1] - positions[0][1]
        n = len(positions) - 1
        return (dx / n, dy / n)

    vax, vay = avg_velocity_vector(a)
    vbx, vby = avg_velocity_vector(b)

    # Relative velocity
    rvx = vax - vbx
    rvy = vay - vby

    # Relative position
    rpx = ax - bx
    rpy = ay - by

    # Dot product: if negative, objects are approaching
    dot = rpx * rvx + rpy * rvy
    if dot >= 0:
        return -1.0  # moving apart

    # TTC = -|relative_position|^2 / (relative_position · relative_velocity)
    rel_pos_sq = rpx**2 + rpy**2
    ttc_frames = -rel_pos_sq / dot
    ttc_seconds = ttc_frames / 15.0  # target_fps

    return ttc_seconds if ttc_seconds > 0 else -1.0
```

---

### `NearMissCandidate`

Internal. Not exposed outside module.

```python
@dataclass
class NearMissCandidate:
    track_id_a: int
    track_id_b: int
    class_label_a: str
    class_label_b: str
    min_distance_px: float
    estimated_ttc_seconds: float     # -1.0 if not applicable
    location_norm: Tuple[float, float]  # normalized midpoint
    frame_count: int                 # how many consecutive frames this pair has been flagged
```

---

### `NearMissBuffer`

Tracks how many consecutive frames each object pair has been in near-miss state.
Prevents single-frame noise from creating false near-miss events.

```python
class NearMissBuffer:
    def __init__(self, min_frames: int = 2):
        # Key: (min_id, max_id) tuple for stable ordering
        self._counts: Dict[Tuple[int,int], int] = {}
        self.min_frames = min_frames

    def update(self, pair: Tuple[int,int]) -> int:
        """Increment count for pair. Return current count."""
        self._counts[pair] = self._counts.get(pair, 0) + 1
        return self._counts[pair]

    def reset(self, pair: Tuple[int,int]) -> None:
        self._counts.pop(pair, None)

    def should_emit(self, pair: Tuple[int,int]) -> bool:
        """True only on the frame count exactly equals min_frames (emit once per event)."""
        return self._counts.get(pair, 0) == self.min_frames

    def cleanup(self, active_pairs: set) -> None:
        """Remove pairs no longer in proximity."""
        stale = [k for k in self._counts if k not in active_pairs]
        for k in stale:
            del self._counts[k]
```

---

### `HeatmapAccumulator`

Maintains a 2D grid of near-miss event density. Persisted to DB so it survives restarts.

```python
class HeatmapAccumulator:
    def __init__(self, grid_size: int = 20):
        self.grid_size = grid_size
        # grid[row][col] = event count
        self._grid: List[List[int]] = [[0]*grid_size for _ in range(grid_size)]

    def record(self, location_norm: Tuple[float, float]) -> None:
        """Map normalized location to grid cell and increment."""
        x, y = location_norm
        col = min(int(x * self.grid_size), self.grid_size - 1)
        row = min(int(y * self.grid_size), self.grid_size - 1)
        self._grid[row][col] += 1

    def get_grid(self) -> List[List[int]]:
        return self._grid

    def to_points(self) -> List[dict]:
        """Flatten to list of {x, y, weight} for dashboard rendering."""
        points = []
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                if self._grid[r][c] > 0:
                    points.append({
                        "x": (c + 0.5) / self.grid_size,
                        "y": (r + 0.5) / self.grid_size,
                        "weight": self._grid[r][c]
                    })
        return points
```

---

### `NearMissTracker`

```python
class NearMissTracker:
    def __init__(self, profile: dict, data_store):
        self.analyzer = TrajectoryAnalyzer(profile)
        self.buffer = NearMissBuffer(
            min_frames=profile.get("near_miss_min_frames", 2)
        )
        self.heatmap = HeatmapAccumulator(grid_size=20)
        self.store = data_store

    def process(self, tracked_frame: TrackedFrame) -> List[NearMissEvent]:
        """
        Analyze frame for near-misses.
        Write confirmed events to data_store.
        Update heatmap.
        Return list of emitted NearMissEvents (may be empty).
        """
        candidates = self.analyzer.analyze(tracked_frame)
        active_pairs = {(min(c.track_id_a, c.track_id_b),
                         max(c.track_id_a, c.track_id_b)) for c in candidates}

        emitted = []
        for candidate in candidates:
            pair = (min(candidate.track_id_a, candidate.track_id_b),
                    max(candidate.track_id_a, candidate.track_id_b))
            self.buffer.update(pair)
            if self.buffer.should_emit(pair):
                event = self._build_event(tracked_frame, candidate)
                self.store.save_near_miss(event)
                self.heatmap.record(candidate.location_norm)
                emitted.append(event)

        self.buffer.cleanup(active_pairs)
        return emitted

    def _build_event(self, frame: TrackedFrame, c: NearMissCandidate) -> NearMissEvent:
        return NearMissEvent(
            event_id              = str(uuid.uuid4()),
            timestamp             = frame.timestamp,
            source_id             = frame.source_id,
            track_id_a            = c.track_id_a,
            track_id_b            = c.track_id_b,
            class_label_a         = c.class_label_a,
            class_label_b         = c.class_label_b,
            min_distance_px       = c.min_distance_px,
            estimated_ttc_seconds = c.estimated_ttc_seconds,
            location_norm         = c.location_norm,
            resolved              = True,
        )

    def get_heatmap_points(self) -> List[dict]:
        return self.heatmap.to_points()
```

---

## Config Keys (from Profile)

```yaml
# config/profiles/campus.yaml
rules:
  near_miss_proximity_px: 80
  near_miss_ttc_threshold_seconds: 1.5
  near_miss_min_frames: 2
```

---

## Retroactive `resolved=False`

When an incident fires (severity score ≥ 61), `main.py` checks if any `NearMissRecord`
was emitted in the last 2 seconds from the same `source_id` involving the same `track_ids`.
If found, `data_store.mark_near_miss_unresolved(event_id)` sets `resolved=False`.

This connects near-miss history to incident records for analyst review.

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Single object in frame (no pairs) | Returns empty list immediately |
| TTC calculation fails | Log WARNING, set `estimated_ttc_seconds=-1.0`, still emit if proximity triggered |
| DB write fails | Log ERROR, continue processing — do not crash loop |

---

## Tests — `tests/test_nearmiss_tracker.py`

| Test | Assertion |
|------|-----------|
| `test_no_event_single_object` | Single object → no NearMissEvent emitted |
| `test_no_event_distant_objects` | Objects > threshold apart → no event |
| `test_event_emitted_at_min_frames` | Event emitted exactly at `min_frames` consecutive close frames |
| `test_not_emitted_before_min_frames` | No event on first frame of proximity |
| `test_heatmap_records_location` | After event, `get_heatmap_points()` non-empty |
| `test_heatmap_grid_cell_correct` | Location maps to correct grid cell |
| `test_buffer_cleaned_when_separated` | Count resets when pair moves out of threshold |
| `test_ttc_negative_when_moving_apart` | TTC = -1.0 when objects diverging |
| `test_db_save_called` | `data_store.save_near_miss` called once per emitted event |

---

## Done When

- Two objects passing within `near_miss_proximity_px` for ≥ 2 frames triggers a `NearMissRecord`
- `NearMissRecord` appears in DB query
- `get_heatmap_points()` returns correct spatial data
- Heatmap visible on dashboard at `/heatmap` endpoint