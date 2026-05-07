# Spec — camera_manager.py (Layer 1)

**Module:** `core/camera_manager.py`  
**Layer:** 1 — Input  
**Input:** Physical camera / video file  
**Output:** `FrameMetadata` → `FrameBuffer` (queue)  
**Depends on:** Nothing (first in pipeline)  
**Used by:** `inference_engine.py`

---

## Responsibility

Own everything between the physical camera and the rest of the system.
Capture frames, wrap them in `FrameMetadata`, push to a thread-safe queue.
Handle hardware failures silently — the pipeline never knows the camera hiccuped.

This module has zero awareness of detection, scoring, or alerts.

---

## Classes

### `FrameMetadata`
Defined in `core/models.py`. Do not redefine here.

---

### `CameraSource` (Abstract Base)

```python
from abc import ABC, abstractmethod
import numpy as np

class CameraSource(ABC):
    @abstractmethod
    def read(self) -> np.ndarray | None:
        """Return a BGR frame or None on failure."""
        ...

    @abstractmethod
    def release(self) -> None:
        """Release hardware/file resources."""
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        ...
```

---

### `USBCameraSource(CameraSource)`

```python
class USBCameraSource(CameraSource):
    def __init__(self, device_index: int = 0, resolution: tuple = (640, 480)):
        ...
```

| Behaviour | Detail |
|-----------|--------|
| Backend | `cv2.VideoCapture(device_index)` |
| Resolution | Set via `CAP_PROP_FRAME_WIDTH` / `CAP_PROP_FRAME_HEIGHT` at init |
| Read failure | Returns `None` — caller handles retry |
| Release | Calls `cap.release()` |

---

### `IPCameraSource(CameraSource)`

```python
class IPCameraSource(CameraSource):
    def __init__(self, rtsp_url: str):
        ...
```

| Behaviour | Detail |
|-----------|--------|
| Backend | `cv2.VideoCapture(rtsp_url)` |
| Reconnect | On `None` read, attempts `VideoCapture(rtsp_url)` — up to 3 times |
| Timeout | 5s per reconnect attempt |

---

### `FileSource(CameraSource)`

```python
class FileSource(CameraSource):
    def __init__(self, path: str, target_fps: int = 15, loop: bool = True):
        ...
```

| Behaviour | Detail |
|-----------|--------|
| Backend | `cv2.VideoCapture(path)` |
| Loop | On EOF, resets to frame 0 if `loop=True` — enables continuous testing |
| FPS throttle | Sleeps `1/target_fps` seconds between reads to simulate real camera rate |
| Use case | Testing and demo without live hardware — default in `settings.yaml` |

---

### `CameraManager`

```python
class CameraManager:
    def __init__(self, source: CameraSource, source_id: str = "cam_01", buffer_size: int = 30):
        ...

    def start(self) -> None:
        """Start background capture thread."""
        ...

    def stop(self) -> None:
        """Signal capture thread to stop, join, release source."""
        ...

    def get_frame(self, timeout: float = 1.0) -> FrameMetadata:
        """Block until a frame is available or timeout raises queue.Empty."""
        ...

    @property
    def buffer_size(self) -> int:
        ...

    @property
    def dropped_frames(self) -> int:
        """Count of frames dropped because buffer was full."""
        ...
```

#### Internal Behaviour

**Capture thread:**
```
loop:
    frame = source.read()
    if frame is None:
        retry_count += 1
        if retry_count >= 3:
            log ERROR "Camera read failed 3 times, sleeping 2s"
            sleep(2)
            retry_count = 0
        continue
    retry_count = 0
    meta = FrameMetadata(uuid4, utcnow, source_id, frame)
    if buffer.full():
        dropped_frames += 1
        log WARNING "FrameBuffer full, dropping frame"
    else:
        buffer.put(meta)
```

**Buffer:** `queue.Queue(maxsize=buffer_size)` — thread-safe, bounded.  
**Thread:** `daemon=True` — dies automatically when main process exits.  
**Frame drop policy:** Drop newest frame when full (camera runs ahead of inference). Log drop count.

---

## Config Keys

```yaml
camera:
  source_type: file        # "file" | "usb" | "rtsp"
  source_id: cam_01
  device_index: 0          # used when source_type: usb
  rtsp_url: null           # used when source_type: rtsp
  file_path: tests/sample.mp4  # used when source_type: file
  target_fps: 15
  resolution: [640, 480]
  buffer_size: 30
```

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Camera not found at startup | Raise `RuntimeError` immediately — do not silently fail |
| Single read failure | Log WARNING, retry up to 3 times |
| 3 consecutive read failures | Log ERROR, sleep 2s, continue retrying |
| Buffer full | Log WARNING, increment `dropped_frames`, continue |
| `get_frame()` timeout | Raises `queue.Empty` — caller handles |

---

## Scalability Hook

`source_id` field on every `FrameMetadata` means all downstream modules are already
multi-camera aware. Adding a second camera in the major project means:
- Instantiate a second `CameraManager` with `source_id="cam_02"`
- Run a second processing thread consuming from it
- Zero changes to any downstream module

---

## Tests — `tests/test_camera_manager.py`

| Test | Assertion |
|------|-----------|
| `test_file_source_reads_frames` | `FileSource.read()` returns non-None ndarray |
| `test_frame_metadata_fields` | All 4 fields populated, `frame_id` is valid UUID |
| `test_source_id_propagated` | `FrameMetadata.source_id` matches constructor arg |
| `test_buffer_does_not_block` | `get_frame()` returns within 2s from `FileSource` |
| `test_loop_behavior` | `FileSource` loops — frame 0 returned after EOF |
| `test_drop_on_full_buffer` | `dropped_frames` increments when buffer saturated |
| `test_stop_joins_thread` | `stop()` completes within 2s, no hanging threads |

---

## Done When

- `FileSource` reads `tests/sample.mp4` and loops
- `CameraManager.start()` fills the buffer continuously
- `get_frame()` returns `FrameMetadata` with all fields populated
- Detection results print to console when wired to `inference_engine`