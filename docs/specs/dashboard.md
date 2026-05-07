# Module Spec: dashboard

## Purpose
Local web UI — live annotated camera feed, incident log, near-miss heatmap, severity chart, and alert controls. FastAPI backend + plain HTML/JS frontend. No cloud dependency, runs entirely on the edge device.

## Location
`dashboard/main.py` + `dashboard/static/`

## Responsibilities
- Stream annotated MJPEG feed from the latest processed frame
- Serve REST endpoints for incidents, near-misses, stats
- Push live SeverityResult events to browser via WebSocket
- Handle acknowledge + false-positive actions from UI
- Never write to core data pipeline — read-only from data_store, write-only to alert acknowledgements

## REST API

| Method | Path                              | Returns                          |
|--------|-----------------------------------|----------------------------------|
| GET    | `/feed`                           | MJPEG stream (annotated frame)   |
| GET    | `/incidents?limit=50&offset=0`    | paginated incident list          |
| GET    | `/near-misses`                    | near-miss log + heatmap points   |
| GET    | `/heatmap`                        | `[{x, y}]` normalized coords    |
| GET    | `/stats`                          | counts, severity histogram       |
| POST   | `/incidents/{id}/ack`             | mark acknowledged                |
| POST   | `/incidents/{id}/false-positive`  | mark false positive              |
| WS     | `/ws/events`                      | live SeverityResult stream       |

## MJPEG Feed
```python
@app.get("/feed")
def video_feed():
    def generate():
        while True:
            frame = frame_store["annotated"]   # set by main.py after inference
            if frame is None:
                time.sleep(0.033)
                continue
            _, buf = cv2.imencode(".jpg", frame)
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                   + buf.tobytes() + b"\r\n")
    return StreamingResponse(generate(),
        media_type="multipart/x-mixed-replace; boundary=frame")
```

## WebSocket Event Stream
```python
@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    while True:
        event = await event_queue.get()   # asyncio.Queue fed from main loop
        await websocket.send_json(event)
```

## Frame Annotation (done in main.py before putting in frame_store)
- Draw bounding boxes: green for low severity, orange for flag, red for alert
- Label: `{class_label} #{track_id}` above each box
- Overlay severity score in top-left corner when score > 30
- Near-miss zone: blue dashed rectangle around involved objects

## Frontend: `dashboard/static/index.html`
Single-file HTML — no build step, no framework dependency.

### Panels
1. **Live Feed** — `<img src="/feed" />` — browser handles MJPEG natively
2. **Incident Table** — fetched from `/incidents` every 5s
   - Columns: Time | Type | Score | Camera | Actions
   - Row color: white (silent), yellow (flag), red (alert)
   - Actions: Acknowledge button, False Positive button
3. **Near-Miss Heatmap** — `<canvas>` overlay on a static reference frame
   - Points from `/heatmap` rendered as translucent red circles
   - Accumulates — gets denser over time at hotspot zones
4. **Severity Chart** — last 1 hour, bar chart using `Chart.js` CDN
   - X: time buckets (5-min intervals)
   - Y: max severity score in that bucket
5. **Live Alert Banner** — WebSocket feed, flashes red when `action_tier === "alert"`

### JS Pattern (no framework)
```javascript
// Incident table — poll every 5s
setInterval(async () => {
    const data = await fetch('/incidents').then(r => r.json());
    renderTable(data);
}, 5000);

// Live events — WebSocket
const ws = new WebSocket(`ws://${location.host}/ws/events`);
ws.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.action_tier === 'alert') showAlertBanner(ev);
};
```

## Shared State (injected from main.py)
```python
# dashboard/state.py
frame_store = {"annotated": None}       # latest annotated frame (np.ndarray)
event_queue = asyncio.Queue(maxsize=100) # SeverityResult dicts
data_store_ref = {"store": None}        # DataStore instance
```
`main.py` imports these and sets them before starting uvicorn in a thread.

## Startup
```python
# in main.py
import uvicorn, threading
from dashboard.main import app
from dashboard import state

state.data_store_ref["store"] = data_store
threading.Thread(
    target=uvicorn.run,
    args=(app,),
    kwargs={"host": "0.0.0.0", "port": 8000},
    daemon=True
).start()
```
Access at `http://<device-ip>:8000`

## Config
```yaml
dashboard:
  host: 0.0.0.0
  port: 8000
  feed_jpeg_quality: 75
```

## Scalability Hooks
- MJPEG stream works for demo/LAN. In major project: replace with HLS stream (ffmpeg) for multi-client support
- WebSocket event queue is source_id-aware — multi-camera events can be filtered per client in major project
- REST API is already paginated (`limit` + `offset`) — ready for high-volume incident logs

## Constraints
- Dashboard NEVER imports from core modules directly — only from `dashboard/state.py` and `data_store` query methods
- No business logic in dashboard — no severity scoring, no rule evaluation
- No auth for minor project — add HTTP Basic Auth for major project deployment

## Testing
- Use FastAPI `TestClient` for all REST endpoints
- Seed `data_store_ref["store"]` with in-memory DB fixture
- Assert `/incidents` returns correct shape and types
- Assert `/heatmap` returns `[{x: float, y: float}]`
- WebSocket: use `starlette.testclient` WebSocket context to assert events are pushed after queue insertion