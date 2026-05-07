# Config Reference: settings.yaml

Every key the system reads, what it does, and what values are valid. No magic strings anywhere else in the codebase — all config flows through here.

## Full Example
```yaml
camera:
  source_type: file       # usb | rtsp | file
  device_index: 0         # for usb only
  rtsp_url: null          # for rtsp only, e.g. "rtsp://192.168.1.10:554/stream"
  file_path: tests/sample.mp4   # for file only
  source_id: cam_01       # unique camera identifier, used in all records
  target_fps: 15
  resolution: [640, 480]
  buffer_maxsize: 30      # max frames in FrameBuffer before dropping

inference:
  model_path: models/yolov8n.onnx
  model_format: onnx      # pt | onnx | tflite
  confidence_threshold: 0.5
  iou_threshold: 0.45
  classes_of_interest:
    - person
    - car
    - motorcycle
    - truck
    - bus

tracker:
  window_seconds: 5       # TrackState history window
  stationary_velocity_px: 5.0   # px/frame below = stationary
  fps: 15                 # used to convert frame count → seconds

profile: campus           # loads config/profiles/campus.yaml

severity:
  rules:
    PersonOnGround:
      aspect_ratio_threshold: 1.5    # bbox width/height > this = lying down
      score: 50
    PersonStationary:
      duration_seconds: 4
      score: 20
    VehicleCollision:
      overlap_required: true
      score: 60
    SuddenStop:
      velocity_drop_ratio: 0.6      # velocity drops >60% in 1 frame
      score: 30
    PersonVehicleProximity:
      distance_px: 80
      score: 25
    Nighttime:
      start_hour: 21
      end_hour: 5
      score_modifier: 10
  tiers:
    silent: [0, 30]
    flag: [31, 60]
    alert: [61, 100]

nearmiss:
  proximity_px: 60        # min distance to flag as near-miss
  ttc_threshold_seconds: 2.0    # time-to-collision below this = flag

alerts:
  telegram_token: ""      # from @BotFather
  telegram_chat_id: ""    # your personal or group chat ID
  cooldown_seconds: 30    # suppress repeat alerts for same event type
  gpio_pin: 17            # BCM pin number
  gpio_flag_duration_ms: 500
  channels:               # which channels are active
    - telegram
    - gpio

storage:
  db_path: data/safety.db
  snapshot_path: data/snapshots
  retention_hours: 24     # raw frame rows pruned after this

dashboard:
  host: 0.0.0.0
  port: 8000
  feed_jpeg_quality: 75
```

## Key Notes

### camera.source_type
- `file` — use for all development and testing. Loops the video automatically.
- `usb` — switches to live webcam. Set `device_index: 0` for first camera.
- `rtsp` — IP camera. Provide full RTSP URL. This is the major-project scalability hook.

### camera.source_id
Propagated through every dataclass (`FrameMetadata.source_id` → `DetectionResult.source_id` → ... → `IncidentRecord.source_id`). In multi-camera mode (major project), each camera gets a unique source_id and the rest of the pipeline is already multi-camera aware.

### profile
Points to `config/profiles/{profile}.yaml`. The profile file overrides proximity thresholds, ignored classes, and near-miss rules for the deployment context (campus, road, factory).

### severity.rules
Each rule entry has a score contribution. Rules are additive, total capped at 100. To add a new rule: add a YAML entry here + implement the corresponding function in `severity_engine.py`. Zero changes to any other module.

### alerts.channels
List of active channels. Removing `gpio` from the list disables GPIO without touching code — useful for running on a laptop without hardware.

### storage.retention_hours
Only applies to raw `frames` table rows. `incidents`, `near_misses`, and `alerts` tables are kept permanently. Snapshot JPEGs referenced by incidents are also kept permanently.

## Loading Pattern
```python
import yaml
from pathlib import Path

def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    profile_path = Path("config/profiles") / f"{cfg['profile']}.yaml"
    with open(profile_path) as f:
        cfg["profile_data"] = yaml.safe_load(f)
    return cfg
```
Config is loaded once in `main.py` and passed to each module constructor. No module reads the file directly.

## Environment Overrides
For secrets (tokens, credentials), use environment variables instead of committing values to settings.yaml:
```bash
export TELEGRAM_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"
```
```python
import os
token = os.getenv("TELEGRAM_TOKEN") or cfg["alerts"]["telegram_token"]
```