# Deployment Guide

> **Note on Implementation**: The project is currently deployed and tested in a **Development/Laptop Simulation** environment. The production deployment steps below (Systemd, Jetson/Pi specific configs) are deferred until physical hardware is introduced.
## Minor Project: Single-Node Edge Deployment

### Prerequisites
- Jetson Nano 4GB or Raspberry Pi 5 (8GB)
- USB webcam or Pi Camera Module 3
- MicroSD card (32GB+ Class 10) or NVMe SSD (Jetson)
- Project dependencies installed (see `hardware_setup.md`)
- `models/yolov8n.onnx` present
- `config/settings.yaml` configured with real Telegram token + GPIO pin

### First-time Setup
```bash
git clone <repo-url> safety-monitor
cd safety-monitor
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Create directories
mkdir -p data/snapshots models

# Download + export model
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"
mv yolov8n.onnx models/

# Test camera
python -c "import cv2; cap = cv2.VideoCapture(0); ok, _ = cap.read(); print('Camera OK:', ok)"

# Run
python main.py
```

### Verify Deployment
Open browser to `http://<device-ip>:8000`
- Live feed should appear within 3 seconds
- Walk in front of camera — bounding box should appear
- Lie down in front of camera for 6+ seconds — Telegram alert should fire

### Run as System Service (auto-start on boot)
```ini
# /etc/systemd/system/safety-monitor.service
[Unit]
Description=Safety Monitor
After=network.target

[Service]
WorkingDirectory=/home/pi/safety-monitor
ExecStart=/home/pi/safety-monitor/venv/bin/python main.py
Restart=on-failure
RestartSec=5
Environment=TELEGRAM_TOKEN=your-token
Environment=TELEGRAM_CHAT_ID=your-chat-id

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable safety-monitor
sudo systemctl start safety-monitor
sudo journalctl -u safety-monitor -f   # follow logs
```

---

## Development: Laptop (No Hardware)

```yaml
# settings.yaml overrides for laptop
camera:
  source_type: file
  file_path: tests/sample.mp4

alerts:
  channels: []   # no GPIO, no Telegram (or add real token for Telegram testing)
```

```bash
python main.py
# Dashboard at http://localhost:8000
```

Everything works except GPIO. Telegram works if you add a real token.

---

## Scaling to Major Project (notes for future)

| Component | Minor (now) | Major (later) |
|-----------|-------------|---------------|
| Camera | 1x USB/RTSP | N cameras, `source_id` already in all records |
| Storage | SQLite local | PostgreSQL — change connection string only |
| Dashboard | Local only | Cloud FastAPI + React frontend |
| Inference | YOLOv8n ONNX | Custom fine-tuned model via retraining pipeline |
| Alerts | Telegram + GPIO | Mobile app push notifications |
| Config | campus.yaml | Per-node profiles loaded from cloud config |

The typed data pipeline (FrameMetadata → DetectionResult → TrackedFrame → SeverityResult) requires zero changes for multi-camera — `source_id` is already propagated through every record.