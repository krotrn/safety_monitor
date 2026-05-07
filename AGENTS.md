# AGENTS.md — Claude Code Instructions for Single-Node Safety Monitor

This file tells Claude Code how to work inside this project.
Read this entire file before writing any code, creating any file, or running any command.

---

## Project Overview

A real-time safety monitoring system that ingests a camera feed, detects incidents using YOLOv8,
scores severity (0–100), triggers alerts via Telegram and GPIO, logs everything to SQLite,
and serves a live dashboard via FastAPI.

Full spec: `docs/PRD.md`  
Architecture: `ARCHITECTURE.md`  
Data models: `docs/data_models.md`

---

## Repository Structure

```
safety-monitor/
├── AGENTS.md                  ← you are here
├── README.md
├── ARCHITECTURE.md
├── PRD.md
├── main.py                    ← entry point, wires all modules together
├── requirements.txt
├── config/
│   ├── settings.yaml          ← runtime config (camera, model, alerts)
│   └── profiles/
│       └── campus.yaml        ← context profile for campus deployment
├── core/
│   ├── camera_manager.py      ← Layer 1
│   ├── inference_engine.py    ← Layer 2
│   ├── object_tracker.py      ← Layer 3
│   ├── severity_engine.py     ← Layer 4
│   ├── nearmiss_tracker.py    ← Layer 5
│   ├── alert_manager.py       ← Layer 6
│   └── data_store.py          ← Layer 7
├── dashboard/
│   ├── main.py                ← FastAPI app
│   └── static/
│       └── index.html         ← single-file frontend
├── models/
│   └── yolov8n.onnx           ← model weights (not committed to git)
├── data/
│   ├── safety.db              ← SQLite database (not committed to git)
│   └── snapshots/             ← JPEG incident frames (not committed to git)
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── data_models.md
│   ├── config_reference.md
│   ├── build_order.md
│   ├── hardware_setup.md
│   ├── deployment.md
│   └── specs/
│       ├── camera_manager.md
│       ├── inference_engine.md
│       ├── object_tracker.md
│       ├── severity_engine.md
│       ├── nearmiss_tracker.md
│       ├── alert_manager.md
│       ├── data_store.md
│       └── dashboard.md
└── tests/
    ├── sample.mp4             ← test video (not committed to git)
    ├── test_camera_manager.py
    ├── test_inference_engine.py
    ├── test_object_tracker.py
    ├── test_severity_engine.py
    ├── test_nearmiss_tracker.py
    ├── test_alert_manager.py
    └── test_data_store.py
```

---

## Module Boundaries — CRITICAL

Each file in `core/` is a sealed module. These are the rules:

### Rule 1: Never import across non-adjacent layers
The data flows in one direction only:

```
camera_manager → inference_engine → object_tracker → severity_engine → nearmiss_tracker → alert_manager → data_store
```

`camera_manager.py` must never import from `severity_engine.py`.  
`alert_manager.py` must never import from `inference_engine.py`.  
Only adjacent layers may reference each other's output types.

### Rule 2: Never modify a data model from a downstream module
Data models are defined in `docs/data_models.py` (single source of truth).
No module may add fields to `FrameMetadata`, `DetectionResult`, `TrackedFrame`, or `SeverityResult`
without updating `docs/data_models.md` first.

### Rule 3: Never put business logic in `main.py`
`main.py` only wires modules together. It instantiates classes, connects queues, starts threads.
No detection logic, no scoring logic, no alert logic belongs there.

### Rule 4: Never hardcode config values
All thresholds, paths, tokens, and parameters must be read from `config/settings.yaml`
or `config/profiles/campus.yaml`. If you are tempted to write a magic number, put it in config.

### Rule 5: `dashboard/` is read-only relative to `core/`
The dashboard reads from `data_store`. It never writes to any `core/` module directly.
The only write the dashboard performs is: acknowledge alert, mark false positive — both via `DataStore` methods.

---

## Data Models (Canonical)

These are the typed structures passed between layers. Do not change their field names.
Add new fields only by appending — never rename or remove existing fields.

```python
# Layer 1 output
@dataclass
class FrameMetadata:
    frame_id: str          # uuid4
    timestamp: str         # ISO8601 UTC
    source_id: str         # e.g. "cam_01"
    raw_frame: np.ndarray

# Layer 2 output
@dataclass
class Detection:
    object_id: str
    class_label: str
    confidence: float
    bbox: List[int]        # [x1, y1, x2, y2] pixels
    bbox_norm: List[float] # [x1, y1, x2, y2] 0.0–1.0

@dataclass
class DetectionResult:
    frame_id: str
    timestamp: str
    source_id: str
    detections: List[Detection]

# Layer 3 output
@dataclass
class TrackedDetection(Detection):
    track_id: int
    positions: List[Tuple[float, float]]  # recent center points
    velocities: List[float]               # recent frame-to-frame speeds
    is_stationary: bool
    stationary_duration: float            # seconds

@dataclass
class TrackedFrame:
    frame_id: str
    timestamp: str
    source_id: str
    raw_frame: np.ndarray
    detections: List[TrackedDetection]

# Layer 4 output
@dataclass
class SeverityResult:
    frame_id: str
    timestamp: str
    source_id: str
    severity_score: float          # 0.0–100.0
    event_type: str                # highest-contributing rule name
    triggered_rules: List[str]
    action_tier: str               # "silent" | "flag" | "alert"
    snapshot: np.ndarray           # raw frame for saving
```

---

## Coding Conventions

### Language & Version
- Python 3.10+
- Type hints on every function signature — no bare `def foo(x)`
- Dataclasses for all structured data — no raw dicts passed between modules

### Style
- PEP8. Max line length 100.
- Imports: stdlib → third-party → local, separated by blank lines
- No `print()` for runtime output — use Python `logging` module
- Logger name = module name: `logger = logging.getLogger(__name__)`

### Error Handling
- Camera disconnect: retry 3 times with 2s backoff, then log error and continue
- Inference failure on a frame: log warning, skip frame, do not crash the loop
- DB write failure: log error, do not crash — incidents are important but the loop must continue
- Alert dispatch failure: log error, mark alert as failed in DB, do not retry automatically

### Threading Model
- `camera_manager` runs capture in a daemon thread
- `inference_engine` runs in its own thread, pulls from `FrameBuffer`
- Everything downstream (tracker → severity → alert → store) runs sequentially in a processing thread
- Dashboard runs in a separate thread via `uvicorn`
- Use `queue.Queue` for inter-thread communication — never share raw frame objects across threads

### Config Loading
```python
import yaml

def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
```
Load config once at startup in `main.py`. Pass relevant sections to each module constructor.
No module reads the config file directly — it receives its config as a dict argument.

---

## Build Order

When implementing features, follow this sequence strictly.
Do not start Phase N+1 until Phase N passes its acceptance test.

| Phase | Module(s) | Done When |
|-------|-----------|-----------|
| 0 | Project setup | `python main.py` runs without error |
| 1 | `camera_manager` + `inference_engine` | Detections print to console from `tests/sample.mp4` |
| 2 | `object_tracker` | Same person holds same `track_id` across 50+ consecutive frames |
| 3 | `data_store` | Manually inserted incident record returned by `get_incidents()` |
| 4 | `severity_engine` | Person-on-ground in test video scores ≥ 70, record saved to DB |
| 5 | `alert_manager` | Telegram receives photo + score within 5s of Alert tier event |
| 6 | `dashboard` | Browser shows live feed + incident table, new incidents appear without refresh |
| 7 | `nearmiss_tracker` + GPIO | Near-miss logged, heatmap renders, buzzer triggers on hardware |

---

## What NOT To Do

- **Do not** install new dependencies without adding them to `requirements.txt`
- **Do not** write inference logic in `object_tracker.py` — inference belongs in `inference_engine.py`
- **Do not** call `alert_manager` from `severity_engine` — `main.py` wires these together
- **Do not** store `np.ndarray` objects in SQLite — save as JPEG, store the file path
- **Do not** use `asyncio` in `core/` modules — only `dashboard/` uses async
- **Do not** use `global` variables — pass state through constructors and method arguments
- **Do not** commit `data/`, `models/`, or `tests/sample.mp4` to git — add to `.gitignore`
- **Do not** hardcode Telegram token or chat ID anywhere — read from `config/settings.yaml`
- **Do not** add cloud API calls to any `core/` module — edge-only inference is a hard requirement

---

## Testing Instructions

Each module has a corresponding test file in `tests/`.

Run all tests:
```bash
pytest tests/ -v
```

Run a single module test:
```bash
pytest tests/test_severity_engine.py -v
```

Every test file must:
- Use a `FileSource` pointed at `tests/sample.mp4` — never require live hardware to test
- Mock `alert_manager` — tests must not send real Telegram messages
- Mock `RPi.GPIO` — tests must not require physical GPIO pins
- Assert on the typed output dataclass fields, not on print output

---

## Dependencies

```
opencv-python
ultralytics
fastapi
uvicorn
sqlalchemy
pyyaml
python-telegram-bot
RPi.GPIO          # mock in tests on non-Pi hardware
pytest
```

Install:
```bash
pip install -r requirements.txt
```

Export model to ONNX before first run:
```python
from ultralytics import YOLO
YOLO("yolov8n.pt").export(format="onnx")
# move yolov8n.onnx to models/
```

---

## Git Conventions

Branch naming:
- `feature/camera-manager`
- `feature/inference-engine`
- `fix/tracker-id-reset`

Commit message format:
```
[module] short description

- what changed
- why
```

Example:
```
[severity_engine] add SuddenStop rule

- detects vehicle velocity drop > 60% in 1s
- adds +30 to severity score
- covered by test_severity_engine.py::test_sudden_stop
```

---

## Context Profile Format

`config/profiles/campus.yaml`:
```yaml
profile: campus
rules:
  person_on_ground_threshold_seconds: 4
  vehicle_sudden_stop_decel_threshold: 0.6
  near_miss_proximity_px: 80
  person_vehicle_proximity_px: 80
  nighttime_start_hour: 21
  nighttime_end_hour: 5
  ignore_classes: []
```

To add a new rule: add the threshold here, add the evaluator function to `severity_engine.py`,
update `docs/specs/severity_engine.md`. No other files need to change.

---

## Quick Reference — Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `CameraManager` | `core/camera_manager.py` | Frame capture + FrameBuffer |
| `FileSource` | `core/camera_manager.py` | Video file input (for testing) |
| `USBCameraSource` | `core/camera_manager.py` | Live USB camera input |
| `InferenceEngine` | `core/inference_engine.py` | YOLOv8 wrapper, returns DetectionResult |
| `ObjectTracker` | `core/object_tracker.py` | Persistent track IDs + TrackState |
| `SeverityEngine` | `core/severity_engine.py` | Rule evaluator, returns SeverityResult |
| `NearMissTracker` | `core/nearmiss_tracker.py` | Trajectory analysis + heatmap |
| `AlertManager` | `core/alert_manager.py` | Telegram + GPIO dispatch + deduplication |
| `DataStore` | `core/data_store.py` | SQLite read/write for all records |
| `app` | `dashboard/main.py` | FastAPI app with MJPEG feed + REST + WebSocket |