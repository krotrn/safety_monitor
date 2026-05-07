# Safety Monitor — Single-Node Edge System

Real-time accident and incident detection on a single edge device. One camera, one Jetson Nano/Pi, end-to-end: detection → severity scoring → alert → dashboard.

## What It Does
- Detects persons, falls, vehicle collisions, and near-misses from a live camera feed
- Scores each event 0–100 (not binary accident/no-accident)
- Sends Telegram photo alerts when severity exceeds threshold
- Triggers physical relay (buzzer/LED) on critical events
- Logs everything to local SQLite with snapshot JPEGs
- Serves a live web dashboard: annotated feed + incident log + near-miss heatmap

## Why It's Not a Tutorial Project
- **Severity score** (0–100) drives proportional response, not binary alarm
- **Near-miss tracking** — flags dangerous events that don't become incidents, builds spatial heatmap
- **Context profiles** — same binary, different rule sets for campus vs road vs factory
- **False-positive logging** — dashboard allows dismissal, seeds future retraining data

## Quick Start (Development — no hardware needed)
```bash
# 1. Clone and enter the repository
git clone <repo> && cd safety-monitor

# 2. Set up virtual environment
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Download and export the YOLO model
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"
mv yolov8n.onnx models/

# 4. Configure your environment
cp config/settings.example.yaml config/settings.yaml
# (Optional) Edit config/settings.yaml to add your Telegram tokens or adjust camera paths

# 5. Run the system
python main.py

# 6. View the Dashboard
# Open http://localhost:8000 in your browser
```

## Architecture
```
Camera → FrameBuffer → InferenceEngine → ObjectTracker
                                              │
                              ┌───────────────┼──────────────────┐
                         SeverityEngine  NearMissTracker    DataStore
                              │
                         AlertManager → Telegram + GPIO
                              │
                          Dashboard (FastAPI + HTML)
```

## Project Structure
```
safety-monitor/
├── core/              # all processing modules
├── dashboard/         # FastAPI backend + static frontend
├── config/
│   ├── settings.yaml  # all config, documented in docs/config_reference.md
│   └── profiles/      # context profiles (campus.yaml, ...)
├── models/            # .onnx weights
├── data/snapshots/    # incident frame JPEGs
├── tests/
├── docs/              # full specs, data models, build order
│   └── specs/         # one .md per module
└── main.py            # entry point
```

## Documentation
| Doc | Contents |
|-----|----------|
| `docs/PRD.md` | Product requirements, user stories, acceptance criteria |
| `AGENTS.md` | Claude Code rules — module boundaries, what not to touch |
| `docs/data_models.md` | All 7 dataclasses + 3 ORM models |
| `docs/specs/` | Per-module specs (responsibilities, API, config, tests) |
| `docs/config_reference.md` | Every settings.yaml key documented |
| `docs/build_order.md` | Priority 0–7 build sequence with acceptance tests |
| `docs/hardware_setup.md` | Jetson/Pi wiring, GPIO, camera placement |
| `docs/test_plan.md` | Unit + integration tests per phase |
| `docs/deployment.md` | Run on device, systemd service, scaling notes |

## Build Order (summary)
0. Project setup + FileSource smoke test
1. camera_manager + inference_engine → detections in console
2. object_tracker → stable IDs across frames
3. data_store → incident saves to DB
4. severity_engine → fall scores >60, saved to DB
5. alert_manager → Telegram photo fires
6. dashboard → live feed + incident table in browser
7. nearmiss_tracker + GPIO → heatmap + physical trigger

## Hardware
- Jetson Nano 4GB (preferred) or Raspberry Pi 5 8GB
- USB webcam or Pi Camera Module 3
- 5V relay module + buzzer/LED

## Roadmap
- **Minor project**: this repo — single node, one camera, campus profile
- **Major project**: multi-camera mesh, cloud sync, mobile app, retraining pipeline
- **SafeGrid**: safety-as-a-service for factories, campuses, municipalities