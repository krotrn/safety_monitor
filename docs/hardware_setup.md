# Hardware Setup

## Recommended Hardware

### Option A: Jetson Nano 4GB (preferred for demo)
- Runs YOLOv8n at 12–18 FPS with ONNX + TensorRT
- Has a dedicated GPU — inference doesn't compete with OS
- GPIO pins built-in for relay/buzzer

### Option B: Raspberry Pi 5 (8GB)
- Runs YOLOv8n at 4–8 FPS (CPU only) — acceptable for 15 FPS target with frame skipping
- GPIO pins available
- Cheaper, easier to source

### Camera
- **USB webcam** (Logitech C270 or similar) — plug-and-play, `source_type: usb`
- **Pi Camera Module 3** — better low-light, requires `libcamera` bridge to OpenCV

### Physical Output
- 5V relay module (single channel)
- 5V buzzer OR LED strip (12V with step-up converter)
- Jumper wires

---

## Jetson Nano Setup

```bash
# Flash JetPack 4.6 SD card image (includes CUDA + cuDNN)
# Boot, run through first-time setup

# Install pip packages
sudo apt update
sudo apt install python3-pip python3-opencv
pip3 install ultralytics fastapi uvicorn sqlalchemy pyyaml python-telegram-bot

# Export YOLOv8n to TensorRT for maximum speed (optional, significant speedup)
from ultralytics import YOLO
YOLO("yolov8n.pt").export(format="engine", device=0)
# Use model_path: models/yolov8n.engine in settings.yaml
```

## Raspberry Pi 5 Setup

```bash
# Flash Raspberry Pi OS (64-bit) with Raspberry Pi Imager
# Enable SSH in Imager settings

sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-opencv libopenblas-dev

pip3 install ultralytics fastapi uvicorn sqlalchemy pyyaml python-telegram-bot RPi.GPIO --break-system-packages

# For Pi Camera Module 3 with OpenCV:
sudo apt install python3-picamera2
# Use PiCameraSource wrapper (convert picamera2 frame to np.ndarray → OpenCV compatible)
```

---

## GPIO Wiring (BCM Numbering)

```
Jetson/Pi GPIO Pin 17 (BCM) ──────► Relay IN
3.3V Pin ────────────────────────► Relay VCC
GND Pin ─────────────────────────► Relay GND

Relay COM ────────── 5V Power (+)
Relay NO ─────────── Buzzer (+)
Buzzer (-) ─────────── GND
```

Test GPIO manually:
```python
import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.OUT)
GPIO.output(17, GPIO.HIGH)   # relay closes, buzzer sounds
import time; time.sleep(1)
GPIO.output(17, GPIO.LOW)
GPIO.cleanup()
```

If no hardware available, set `channels: []` in settings.yaml — GPIO is skipped, everything else works.

---

## Camera Placement (Campus Profile)

- **Parking lot entrance**: captures vehicles + pedestrians crossing — highest incident probability
- **Building entrance staircase**: person fall detection
- **Height**: 2.5–4 metres, angled down 30–45° for best bbox aspect ratios
- **Field of view**: 640×480 covers roughly 8–12m at 3m mounting height

---

## Running the System

```bash
# SSH into device or run directly
cd safety-monitor
source venv/bin/activate

# First time: verify camera sees frames
python -c "import cv2; cap = cv2.VideoCapture(0); print(cap.read()[0])"

# Run
python main.py

# Dashboard accessible at:
http://<device-ip>:8000
```

## Port Forwarding (for remote demo access)
```bash
# On your laptop, tunnel dashboard to localhost:
ssh -L 8000:localhost:8000 pi@<device-ip>
# Then open http://localhost:8000 on your laptop
```