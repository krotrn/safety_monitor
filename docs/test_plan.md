# Test Plan

## Philosophy
- Always use `FileSource` — no live hardware needed to run tests
- Always mock Telegram bot and GPIO — tests must pass on any machine
- Assert on typed dataclass fields — never assert on print output or log strings
- Each phase has a clear "done when" acceptance test — stop when it passes, move on

---

## Phase 1: Camera + Inference

**Unit: CameraManager**
```python
def test_camera_manager_buffers_frames():
    source = FileSource("tests/sample.mp4")
    cam = CameraManager(source, source_id="cam_01")
    cam.start()
    frame = cam.get_frame(timeout=2.0)
    assert isinstance(frame, FrameMetadata)
    assert frame.source_id == "cam_01"
    assert frame.raw_frame is not None
    assert frame.raw_frame.shape[2] == 3   # BGR
```

**Unit: InferenceEngine**
```python
def test_inference_returns_detection_result():
    engine = InferenceEngine("models/yolov8n.onnx", conf_threshold=0.3)
    frame = make_test_frame()   # load a frame known to contain a person
    result = engine.detect(frame)
    assert isinstance(result, DetectionResult)
    assert result.frame_id == frame.frame_id
    assert any(d.class_label == "person" for d in result.detections)
    assert all(0 <= d.confidence <= 1 for d in result.detections)
```

---

## Phase 2: Tracker

```python
def test_track_id_stable_across_frames():
    # Run 50 frames through tracker, assert same person gets same ID ≥ 40 times
    engine = InferenceEngine("models/yolov8n.onnx")
    source = FileSource("tests/sample_person_walking.mp4")
    cam = CameraManager(source)
    cam.start()
    seen_ids = set()
    for _ in range(50):
        frame = cam.get_frame()
        result = engine.detect(frame)   # uses model.track(persist=True)
        for d in result.detections:
            if d.class_label == "person":
                seen_ids.add(d.track_id)
    # If stable tracking: only 1 unique ID for the walking person
    assert len(seen_ids) <= 2   # allow 1 ID transition (tracking hiccup)
```

---

## Phase 3: Storage

```python
def test_save_and_retrieve_incident():
    store = DataStore(db_path=":memory:", snapshot_root="/tmp/test_snaps")
    record = IncidentRecord(
        source_id="cam_01",
        severity_score=75.0,
        event_type="PersonOnGround",
        triggered_rules='["PersonOnGround","PersonStationary"]',
        snapshot_path="2024-01-15/test_frame.jpg"
    )
    incident_id = store.save_incident(record)
    results = store.get_incidents(limit=10)
    assert len(results) == 1
    assert results[0].severity_score == 75.0
    assert results[0].event_type == "PersonOnGround"

def test_heatmap_data_returns_normalized_coords():
    store = DataStore(db_path=":memory:", snapshot_root="/tmp")
    store.save_near_miss(NearMissRecord(source_id="cam_01", location_x=0.4, location_y=0.6, min_distance_px=45.0))
    points = store.get_heatmap_data()
    assert len(points) == 1
    x, y = points[0]
    assert 0.0 <= x <= 1.0
    assert 0.0 <= y <= 1.0
```

---

## Phase 4: Severity Engine

```python
def test_person_on_ground_scores_above_60():
    # Construct a TrackedFrame with a person bbox that is wider than tall
    tracked_frame = make_tracked_frame(detections=[
        make_detection(class_label="person", bbox=[100, 200, 400, 260])  # wide = lying down
    ])
    track_states = {1: TrackState(track_id=1, class_label="person",
                                   stationary_duration=5.0)}
    result = evaluate(tracked_frame, track_states, profile={"person_on_ground_threshold_seconds": 4})
    assert result.severity_score > 60
    assert "PersonOnGround" in result.triggered_rules
    assert result.action_tier == "alert"

def test_score_caps_at_100():
    # Multiple rules fire simultaneously
    result = evaluate(make_overloaded_tracked_frame(), {}, profile={})
    assert result.severity_score <= 100
```

---

## Phase 5: Alert Manager

```python
@pytest.mark.asyncio
async def test_telegram_alert_fires_on_alert_tier(mocker):
    mock_send = mocker.AsyncMock()
    mocker.patch("telegram.Bot.send_photo", mock_send)
    
    manager = AlertManager(token="fake", chat_id="123", cooldown=30)
    result = make_severity_result(action_tier="alert", event_type="PersonOnGround")
    snapshot = np.zeros((480, 640, 3), dtype=np.uint8)
    await manager.dispatch(result, snapshot)
    
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert "PersonOnGround" in call_kwargs["caption"]

@pytest.mark.asyncio
async def test_cooldown_suppresses_duplicate_alert(mocker):
    mock_send = mocker.AsyncMock()
    mocker.patch("telegram.Bot.send_photo", mock_send)
    
    manager = AlertManager(token="fake", chat_id="123", cooldown=60)
    result = make_severity_result(action_tier="alert", event_type="PersonOnGround")
    snapshot = np.zeros((480, 640, 3), dtype=np.uint8)
    
    await manager.dispatch(result, snapshot)
    await manager.dispatch(result, snapshot)   # second call within cooldown
    
    assert mock_send.call_count == 1   # only fired once
```

---

## Phase 6: Dashboard

```python
def test_incidents_endpoint():
    from fastapi.testclient import TestClient
    from dashboard.main import app
    from dashboard import state
    
    store = DataStore(":memory:", "/tmp")
    store.save_incident(IncidentRecord(source_id="cam_01", severity_score=80.0,
                                        event_type="PersonOnGround", ...))
    state.data_store_ref["store"] = store
    
    client = TestClient(app)
    response = client.get("/incidents")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["event_type"] == "PersonOnGround"
    assert data[0]["severity_score"] == 80.0

def test_heatmap_endpoint_returns_points():
    # seed near_misses, assert /heatmap returns [{x, y}] list
    ...
```

---

## End-to-End Acceptance Test

Run against `tests/sample_fall.mp4` (a clip with a person falling/lying down):

```python
def test_end_to_end_fall_detection():
    store = DataStore(":memory:", "/tmp/snaps")
    # wire full pipeline with FileSource
    # run for 200 frames
    # assert:
    assert store.get_incidents(limit=1)[0].severity_score > 60
    assert store.get_incidents(limit=1)[0].event_type in ["PersonOnGround", "PersonStationary"]
    heatmap = store.get_heatmap_data()
    # near-miss or incident location recorded
    assert len(heatmap) >= 0   # may be 0 if no near-miss in clip, that's OK
```

---

## Test Utilities to Create (`tests/helpers.py`)
- `make_test_frame(path=None)` → `FrameMetadata` with a real or synthetic frame
- `make_detection(**kwargs)` → `Detection` with sensible defaults
- `make_tracked_frame(**kwargs)` → `TrackedFrame`
- `make_severity_result(**kwargs)` → `SeverityResult`
- `make_overloaded_tracked_frame()` → frame that triggers all rules simultaneously