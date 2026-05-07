# Spec — inference_engine.py (Layer 2)

**Module:** `core/inference_engine.py`  
**Layer:** 2 — Detection  
**Input:** `FrameMetadata`  
**Output:** `DetectionResult`  
**Depends on:** `core/models.py`  
**Used by:** `object_tracker.py`

---

## Responsibility

Run object detection on every frame. Wrap raw model output into typed `DetectionResult`.
Handle model loading, frame preprocessing, and class filtering.
Know nothing about tracking, scoring, or alerts.

One method does the work: `detect(frame: FrameMetadata) -> DetectionResult`.

---

## Classes

### `FramePreprocessor`

```python
class FramePreprocessor:
    def __init__(self, target_size: tuple = (640, 640)):
        ...

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Resize and normalize frame for model input."""
        ...
```

| Step | Detail |
|------|--------|
| Resize | `cv2.resize(frame, target_size)` — letterbox to preserve aspect ratio |
| Color | Keep BGR — YOLOv8 handles conversion internally |
| Normalize | Not applied here — model handles internally |
| Original size | Preserved as `(h, w)` for bbox denormalization |

Isolated in its own class so preprocessing logic can be swapped without touching the model.

---

### `ModelLoader`

```python
class ModelLoader:
    def __init__(self, model_path: str, model_format: str = "onnx"):
        ...

    def load(self) -> YOLO:
        """Load model once. Raise RuntimeError if file not found."""
        ...
```

| Format | Detail |
|--------|--------|
| `.pt` | PyTorch — development, slower on edge |
| `.onnx` | ONNX — optimized for Jetson and Pi, default for deployment |
| `.tflite` | TFLite — fallback for Pi without GPU |

Model is loaded **once** at startup. Never reloaded per frame.
If model file is missing, raise `RuntimeError` immediately — do not attempt recovery.

---

### `InferenceEngine`

```python
class InferenceEngine:
    def __init__(self, config: dict):
        """
        config keys:
          model_path: str
          model_format: str        # "pt" | "onnx" | "tflite"
          confidence_threshold: float
          classes_of_interest: List[str]
        """
        ...

    def detect(self, frame_meta: FrameMetadata) -> DetectionResult:
        """Run inference. Always returns DetectionResult — never raises on empty detection."""
        ...
```

#### `detect()` Internal Flow

```
1. Preprocess frame (resize)
2. Run model.track(frame, persist=True, conf=threshold, verbose=False)
   — model.track() instead of model() gives persistent IDs for free
   — persist=True maintains tracker state across calls
3. For each box in results[0].boxes:
   a. Get class label from model.names[int(box.cls)]
   b. Skip if label not in classes_of_interest
   c. Skip if confidence < threshold (already filtered by model, but double-check)
   d. Build Detection dataclass
4. Return DetectionResult with all valid detections
```

**Why `model.track()` here instead of a separate tracker?**  
Ultralytics `model.track(persist=True)` maintains ByteTracker state internally across frames.
This gives persistent `track_id` via `box.id` without an external tracker library.
`ObjectTracker` (Layer 3) then enriches with motion history — it does not do the tracking itself.

#### Building a `Detection`

```python
h, w = frame_meta.raw_frame.shape[:2]
x1, y1, x2, y2 = map(int, box.xyxy[0])

Detection(
    object_id  = str(uuid.uuid4()),       # new UUID per detection
    class_label = model.names[int(box.cls)],
    confidence  = float(box.conf),
    bbox        = [x1, y1, x2, y2],
    bbox_norm   = [x1/w, y1/h, x2/w, y2/h],
    track_id    = int(box.id) if box.id is not None else -1,
)
```

Note: `track_id` is included in `Detection` at this stage even though it's formally a Layer 3
concept — this is because `model.track()` produces it here. `ObjectTracker` reads it and
builds the motion history layer on top.

---

## Config Keys

```yaml
inference:
  model_path: models/yolov8n.onnx
  model_format: onnx             # pt | onnx | tflite
  confidence_threshold: 0.5
  target_size: [640, 640]
  classes_of_interest:
    - person
    - car
    - motorcycle
    - truck
    - bus
```

---

## Model Setup (One-Time)

Download and export before first run:

```python
from ultralytics import YOLO
YOLO("yolov8n.pt").export(format="onnx")
# Move yolov8n.onnx → models/yolov8n.onnx
```

On Jetson Nano — use TensorRT export for maximum performance:
```python
YOLO("yolov8n.pt").export(format="engine")  # produces .engine file
```

---

## Performance Targets

| Hardware | Model | Target FPS |
|----------|-------|------------|
| Raspberry Pi 5 | yolov8n.onnx | ≥ 8 FPS |
| Jetson Nano | yolov8n.onnx | ≥ 15 FPS |
| Jetson Nano | yolov8n.engine (TensorRT) | ≥ 25 FPS |
| Dev machine (CPU) | yolov8n.pt | ≥ 5 FPS (acceptable for dev) |

If inference falls below 5 FPS, skip every other frame via config `inference.skip_frames: 1`.

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Model file not found | `RuntimeError` at startup — fast fail |
| Inference exception on frame | Log WARNING, return empty `DetectionResult` — do not crash loop |
| `box.id` is None (tracker lost) | Set `track_id = -1`, still emit Detection |
| All detections filtered (empty frame) | Return `DetectionResult` with `detections=[]` — valid output |

---

## Scalability Hook

`classes_of_interest` is config-driven. Adding PPE detection (hard hat, vest) in the major
project requires only adding class names to config — no code changes.

Model format abstraction means swapping `yolov8n` → `yolov8s` → custom fine-tuned model
requires only a config path change.

---

## Tests — `tests/test_inference_engine.py`

| Test | Assertion |
|------|-----------|
| `test_model_loads` | `InferenceEngine.__init__` completes without error |
| `test_detect_returns_result` | `detect()` returns `DetectionResult` for any frame |
| `test_empty_frame_returns_empty_list` | Blank frame returns `detections=[]`, not None |
| `test_class_filter` | Detections not in `classes_of_interest` are excluded |
| `test_confidence_filter` | Detections below threshold are excluded |
| `test_bbox_norm_in_range` | All `bbox_norm` values between 0.0 and 1.0 |
| `test_frame_id_propagated` | `DetectionResult.frame_id` matches input `FrameMetadata.frame_id` |
| `test_person_detected_in_sample` | At least 1 "person" detected in `tests/sample.mp4` frame 0 |

---

## Done When

- Model loads from `models/yolov8n.onnx` without error
- `detect()` returns `DetectionResult` with correct class labels and bboxes
- Person detected in test video frame with confidence ≥ 0.5
- All `bbox_norm` values within `[0.0, 1.0]`