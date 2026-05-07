# Build Order

Priority sequence for implementing the single-node safety monitor. Build end-to-end skeleton first, then add flesh module by module.

## Philosophy
**A blinking light through all 8 layers on day 1 beats a perfect camera module in isolation.**
Get data flowing end-to-end with stubs before any module is feature-complete.

## Phase Table

| Phase | Module(s)                    | Done When                                                   | Estimated Effort |
|-------|------------------------------|-------------------------------------------------------------|------------------|
| 0     | Project setup                | Folder structure created, deps installed, FileSource plays sample.mp4 | 2–3 hours |
| 1     | camera_manager + inference_engine | Detection results printing to console from video file | 1 day |
| 2     | object_tracker               | Same person keeps same integer ID across 50+ consecutive frames | 1 day |
| 3     | data_store                   | A manually created incident appears in `get_incidents()` query | Half day |
| 4     | severity_engine              | Person lying down in test video scores >60 and saves to DB | 1 day |
| 5     | alert_manager                | Telegram receives photo + caption when score >60           | Half day |
| 6     | dashboard                    | Browser shows live annotated feed + auto-refreshing incident table | 1–2 days |
| 7     | nearmiss_tracker + GPIO      | Near-miss event saves to DB; GPIO relay (simulated via Stub) triggers on alert | 1–2 days |

## Phase 0: Project Setup

```
safety-monitor/
├── config/
│   ├── settings.yaml
│   └── profiles/campus.yaml
├── core/
│   ├── camera_manager.py
│   ├── inference_engine.py
│   ├── object_tracker.py
│   ├── severity_engine.py
│   ├── nearmiss_tracker.py
│   ├── alert_manager.py
│   └── data_store.py
├── dashboard/
│   ├── main.py
│   ├── state.py
│   └── static/index.html
├── models/
├── data/snapshots/
├── tests/
├── main.py
└── requirements.txt
```

```bash
python -m venv venv && source venv/bin/activate
pip install opencv-python ultralytics fastapi uvicorn sqlalchemy \
            pyyaml python-telegram-bot RPi.GPIO
```

Start with `source_type: file` in settings.yaml. Download YOLOv8n and export to ONNX:
```python
from ultralytics import YOLO
YOLO("yolov8n.pt").export(format="onnx")
```

## Phase 1: Camera → Console

Smoke test in `main.py` — no storage, no alerts, just detections printed:
```python
cam = CameraManager(FileSource("tests/sample.mp4"))
engine = InferenceEngine("models/yolov8n.onnx")
cam.start()
while True:
    frame = cam.get_frame()
    result = engine.detect(frame)
    print(result.timestamp, [(d.class_label, round(d.confidence, 2)) for d in result.detections])
```

## Phase 2: Tracker → Stable IDs

Replace `engine.detect()` with `model.track(persist=True)` in InferenceEngine.
Add ObjectTracker with TrackState per ID.
Acceptance: watch output for 50+ frames — person walking through keeps same ID.

## Phase 3: Storage → DB Row

Create DataStore, tables auto-created on init.
Write one fake incident manually, query it back.
```python
store = DataStore("data/safety.db", "data/snapshots")
store.save_incident(IncidentRecord(source_id="cam_01", severity_score=75.0, event_type="test", ...))
print(store.get_incidents())   # must print 1 row
```

## Phase 4: Severity → Saved Incidents

Wire `severity_engine.evaluate()` into the main loop after tracker.
Find or create a test clip with a person lying on the ground (or simulate by holding camera sideways).
Acceptance: `get_incidents()` contains a record with `severity_score > 60` and `event_type = "PersonOnGround"`.

## Phase 5: Alerts → Telegram Photo

Create Telegram bot via @BotFather. Paste token + chat_id into settings.yaml (or env vars).
Wire AlertManager into main loop — receives SeverityResult, dispatches if tier is "alert".
Acceptance: phone receives a Telegram message with camera snapshot and correct caption.

## Phase 6: Dashboard → Browser

Start uvicorn in background thread from main.py. Set `frame_store["annotated"]` after annotating frame.
Open `http://localhost:8000` — see live feed + incident table.
Acceptance: new incident appears in browser table within 5 seconds of being logged to DB.

## Phase 7: Near-Miss + GPIO

Add NearMissTracker into main loop — runs on TrackedFrame, checks proximity/TTC.
Add GPIO relay wiring (Jetson/Pi only — skip on laptop, use StubOutput).
Acceptance: near-miss event visible in `/near-misses` endpoint; physical buzzer triggers on alert-tier incident.

## Integration Test (End-to-End)
Play `tests/sample.mp4` containing a simulated fall event. Confirm:
- [ ] Detection fires with >0.5 confidence on "person"
- [ ] Track ID stays stable for the person across the clip
- [ ] Severity score exceeds 60 for the fall event
- [ ] Incident record saved to DB with snapshot JPEG
- [ ] Telegram message received within 10 seconds
- [ ] Browser incident table shows the event
- [ ] `GET /heatmap` returns at least one point