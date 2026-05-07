# Data Models — Single Source of Truth

**Version:** 1.0  
**Status:** Canonical  
**Last Updated:** 2026-05-06

> This file is the single source of truth for all data structures passed between modules.
> No module may define its own version of these classes.
> All imports must come from a shared `core/models.py` file.
> To change any model, update this doc first, then update `core/models.py`, then update affected modules.

---

## Overview — Data Flow

```
Camera          Layer 1           Layer 2              Layer 3              Layer 4
  │                │                 │                    │                    │
  ▼                ▼                 ▼                    ▼                    ▼
raw frame  →  FrameMetadata  →  DetectionResult  →  TrackedFrame  →  SeverityResult
                                      │                    │                    │
                                 Detection (list)   TrackedDetection      → alert_manager
                                                       (list)             → data_store

Side outputs:
  TrackedFrame  →  NearMissEvent      →  data_store (near_misses table)
  SeverityResult →  AlertRecord       →  data_store (alerts table)
  SeverityResult →  IncidentRecord    →  data_store (incidents table)
```

Every boundary between layers is a typed dataclass.
No raw dicts, no untyped tuples, no positional assumptions.

---

## Layer 1 — camera_manager.py

### `FrameMetadata`

Wraps every frame emitted by the camera manager into the processing pipeline.

```python
from dataclasses import dataclass
import numpy as np

@dataclass
class FrameMetadata:
    frame_id: str          # UUID4 string — unique per frame
    timestamp: str         # ISO8601 UTC — e.g. "2026-05-06T14:32:01.123456"
    source_id: str         # Camera identifier — e.g. "cam_01"
    raw_frame: np.ndarray  # BGR image array, shape (H, W, 3), dtype uint8
```

**Field notes:**

| Field | Type | Notes |
|-------|------|-------|
| `frame_id` | `str` | Generated with `uuid.uuid4()` at capture time |
| `timestamp` | `str` | `datetime.utcnow().isoformat()` — always UTC, never local time |
| `source_id` | `str` | Read from config `camera.source_id` — default `"cam_01"` |
| `raw_frame` | `np.ndarray` | Never resized here — preprocessing happens in `inference_engine` |

**Invariants:**
- `raw_frame` is never `None` — frames with read failures are dropped before wrapping
- `frame_id` is globally unique across the session
- `source_id` is stable for the lifetime of the process

---

## Layer 2 — inference_engine.py

### `Detection`

A single detected object within one frame.

```python
from dataclasses import dataclass
from typing import List

@dataclass
class Detection:
    object_id: str         # UUID4 — unique per detection instance (not persistent across frames)
    class_label: str       # e.g. "person", "car", "motorcycle", "truck", "bus"
    confidence: float      # 0.0–1.0 — model confidence score
    bbox: List[int]        # [x1, y1, x2, y2] in pixels, absolute coordinates
    bbox_norm: List[float] # [x1, y1, x2, y2] normalized 0.0–1.0 relative to frame size
```

**Field notes:**

| Field | Type | Notes |
|-------|------|-------|
| `object_id` | `str` | New UUID per detection — not persistent. Use `track_id` (Layer 3) for persistence |
| `class_label` | `str` | Only classes in `inference.classes_of_interest` config list are emitted |
| `confidence` | `float` | Detections below `inference.confidence_threshold` are filtered before wrapping |
| `bbox` | `List[int]` | `[x1, y1, x2, y2]` — top-left to bottom-right, pixel coordinates |
| `bbox_norm` | `List[float]` | Same corners, divided by frame `(width, height)` — resolution-independent |

**Invariants:**
- `confidence >= inference.confidence_threshold` always (filtered upstream)
- `bbox` values are within frame bounds `[0, W]` and `[0, H]`
- `bbox_norm` values are within `[0.0, 1.0]`
- `len(bbox) == 4` and `len(bbox_norm) == 4` always

---

### `DetectionResult`

All detections for a single frame. Output of `InferenceEngine.detect()`.

```python
@dataclass
class DetectionResult:
    frame_id: str              # Copied from FrameMetadata.frame_id
    timestamp: str             # Copied from FrameMetadata.timestamp
    source_id: str             # Copied from FrameMetadata.source_id
    detections: List[Detection] # May be empty list — never None
```

**Field notes:**

| Field | Type | Notes |
|-------|------|-------|
| `detections` | `List[Detection]` | Empty list `[]` if no objects detected — never `None` |

**Invariants:**
- `frame_id`, `timestamp`, `source_id` always match the originating `FrameMetadata`
- `detections` is always a list, even when empty

---

## Layer 3 — object_tracker.py

### `TrackedDetection`

Extends `Detection` with persistent tracking state. One per detected object per frame.

```python
from dataclasses import dataclass, field
from typing import List, Tuple

@dataclass
class TrackedDetection:
    # All Detection fields (copied, not inherited — avoids dataclass inheritance issues)
    object_id: str
    class_label: str
    confidence: float
    bbox: List[int]
    bbox_norm: List[float]

    # Tracker additions
    track_id: int                          # Persistent integer ID across frames
    center: Tuple[float, float]            # (cx, cy) — center of bbox in pixels
    positions: List[Tuple[float, float]]   # Last N center points (sliding window, ~5s at 15fps)
    velocities: List[float]                # Frame-to-frame pixel distances, same window
    is_stationary: bool                    # True if avg velocity < 5.0 px/frame
    stationary_duration: float             # Seconds object has been continuously stationary
```

**Field notes:**

| Field | Type | Notes |
|-------|------|-------|
| `track_id` | `int` | Assigned by ByteTracker — stable until object leaves frame |
| `center` | `Tuple[float, float]` | `((x1+x2)/2, (y1+y2)/2)` — computed from bbox |
| `positions` | `List[Tuple]` | `deque(maxlen=75)` cast to list — 75 frames ≈ 5s at 15fps |
| `velocities` | `List[float]` | Euclidean distance between consecutive center points |
| `is_stationary` | `bool` | `mean(velocities[-10:]) < 5.0` px/frame |
| `stationary_duration` | `float` | Count of consecutive stationary frames / target_fps |

**Invariants:**
- `track_id >= 0` always — `-1` is never emitted (untracked detections are dropped)
- `len(positions) == len(velocities) + 1` (velocity is difference between positions)
- `stationary_duration == 0.0` if `len(velocities) < 10`

---

### `TrackedFrame`

All tracked detections for a single frame. Output of `ObjectTracker.update()`.

```python
@dataclass
class TrackedFrame:
    frame_id: str
    timestamp: str
    source_id: str
    raw_frame: np.ndarray              # Carried forward from FrameMetadata for snapshot saving
    detections: List[TrackedDetection] # May be empty list — never None
```

**Field notes:**

| Field | Type | Notes |
|-------|------|-------|
| `raw_frame` | `np.ndarray` | Same array reference from `FrameMetadata` — not copied |
| `detections` | `List[TrackedDetection]` | Only detections with valid `track_id` |

---

## Layer 4 — severity_engine.py

### `SeverityResult`

Output of the severity engine for every processed frame. Always produced — even when score is 0.

```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class SeverityResult:
    frame_id: str
    timestamp: str
    source_id: str
    severity_score: float          # 0.0–100.0, additive across rules, capped at 100
    event_type: str                # Name of highest-contributing triggered rule, or "none"
    triggered_rules: List[str]     # All rule names that fired this frame
    action_tier: str               # "silent" | "flag" | "alert"
    snapshot: np.ndarray           # raw_frame from TrackedFrame — for saving to disk
    involved_track_ids: List[int]  # track_ids of objects that contributed to the score
```

**Field notes:**

| Field | Type | Notes |
|-------|------|-------|
| `severity_score` | `float` | Sum of all triggered rule scores, capped at `100.0` |
| `event_type` | `str` | First rule in `triggered_rules`, or `"none"` if list is empty |
| `triggered_rules` | `List[str]` | Empty list `[]` when score is 0 — never `None` |
| `action_tier` | `str` | `"silent"` (0–30) \| `"flag"` (31–60) \| `"alert"` (61–100) |
| `snapshot` | `np.ndarray` | Saved to disk only when `action_tier != "silent"` |
| `involved_track_ids` | `List[int]` | Empty if no tracks contributed (e.g. rule triggered by timing only) |

**Invariants:**
- `severity_score` is always in `[0.0, 100.0]`
- `action_tier` is always one of the three valid strings
- `event_type == "none"` iff `triggered_rules == []`

---

## Side Output — nearmiss_tracker.py

### `NearMissEvent`

Emitted when two tracked objects come within proximity threshold without a full incident.

```python
from dataclasses import dataclass
from typing import Tuple

@dataclass
class NearMissEvent:
    event_id: str                      # UUID4
    timestamp: str                     # ISO8601 UTC
    source_id: str                     # Camera that captured it
    track_id_a: int                    # First object
    track_id_b: int                    # Second object
    class_label_a: str                 # e.g. "person"
    class_label_b: str                 # e.g. "car"
    min_distance_px: float             # Closest approach distance in pixels
    estimated_ttc_seconds: float       # Time-to-collision estimate, -1.0 if not applicable
    location_norm: Tuple[float, float] # (cx, cy) of midpoint, normalized 0.0–1.0
    resolved: bool                     # True = didn't escalate to incident
```

**Field notes:**

| Field | Type | Notes |
|-------|------|-------|
| `estimated_ttc_seconds` | `float` | `-1.0` if objects moving apart or parallel — not approaching |
| `location_norm` | `Tuple[float, float]` | Midpoint of the two bbox centers, normalized — used for heatmap grid |
| `resolved` | `bool` | Always `True` at creation — set to `False` retroactively if incident follows within 2s |

---

## Storage Models — data_store.py

These are SQLAlchemy ORM models. They mirror the processing dataclasses above but are
optimized for SQLite storage (no numpy arrays, no lists — serialized to JSON strings or file paths).

### `IncidentRecord`

```python
from sqlalchemy import Column, String, Float, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base
import uuid
from datetime import datetime

Base = declarative_base()

class IncidentRecord(Base):
    __tablename__ = "incidents"

    id               = Column(String,   primary_key=True, default=lambda: str(uuid.uuid4()))
    frame_id         = Column(String,   nullable=False)
    timestamp        = Column(DateTime, default=datetime.utcnow, index=True)
    source_id        = Column(String,   nullable=False, index=True)
    severity_score   = Column(Float,    nullable=False)
    event_type       = Column(String,   nullable=False, index=True)
    triggered_rules  = Column(Text,     nullable=False)  # JSON: ["Rule1", "Rule2"]
    action_tier      = Column(String,   nullable=False)  # "silent" | "flag" | "alert"
    snapshot_path    = Column(String,   nullable=True)   # Relative path to JPEG
    involved_tracks  = Column(Text,     nullable=True)   # JSON: [1, 4, 7]
    acknowledged     = Column(Boolean,  default=False)
    false_positive   = Column(Boolean,  default=False)
```

### `NearMissRecord`

```python
class NearMissRecord(Base):
    __tablename__ = "near_misses"

    id                    = Column(String,  primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp             = Column(DateTime, default=datetime.utcnow, index=True)
    source_id             = Column(String,  nullable=False)
    track_id_a            = Column(String,  nullable=False)
    track_id_b            = Column(String,  nullable=False)
    class_label_a         = Column(String,  nullable=False)
    class_label_b         = Column(String,  nullable=False)
    min_distance_px       = Column(Float,   nullable=False)
    estimated_ttc_seconds = Column(Float,   nullable=True)
    location_x            = Column(Float,   nullable=False)  # normalized 0.0–1.0
    location_y            = Column(Float,   nullable=False)  # normalized 0.0–1.0
    resolved              = Column(Boolean, default=True)
```

### `AlertRecord`

```python
class AlertRecord(Base):
    __tablename__ = "alerts"

    id                  = Column(String,  primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id         = Column(String,  nullable=False, index=True)  # FK → incidents.id
    timestamp           = Column(DateTime, default=datetime.utcnow)
    channels_triggered  = Column(Text,    nullable=False)  # JSON: ["telegram", "gpio"]
    acknowledged        = Column(Boolean, default=False)
    false_positive      = Column(Boolean, default=False)
    dispatch_latency_ms = Column(Float,   nullable=True)   # ms from detection to dispatch
```

---

## `core/models.py` — Implementation File

All dataclasses above must live in a single file: `core/models.py`.

```python
# core/models.py
# DO NOT add logic to this file. Pure data definitions only.

from dataclasses import dataclass, field
from typing import List, Tuple
import numpy as np

@dataclass
class FrameMetadata: ...

@dataclass
class Detection: ...

@dataclass
class DetectionResult: ...

@dataclass
class TrackedDetection: ...

@dataclass
class TrackedFrame: ...

@dataclass
class SeverityResult: ...

@dataclass
class NearMissEvent: ...
```

Every module imports from here:
```python
from core.models import FrameMetadata, DetectionResult, TrackedFrame, SeverityResult
```

Never define a local version of these classes inside a module file.

---

## Versioning Policy

| Change Type | Action Required |
|-------------|----------------|
| Add a new field (optional, with default) | Update this doc + `core/models.py` + affected module |
| Rename a field | Update this doc + `core/models.py` + ALL modules + ALL tests |
| Remove a field | Requires team sign-off — treat as breaking change |
| Add a new top-level dataclass | Update this doc + `core/models.py` |
| Change a field type | Treat as breaking change — full audit required |

**Current version: 1.0**  
Record all changes in the table below.

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-05-06 | Initial definition of all models |