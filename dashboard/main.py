"""Dashboard — FastAPI app with MJPEG feed, REST endpoints, WebSocket."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import List

import cv2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from dashboard import state

logger = logging.getLogger(__name__)

app = FastAPI(title="Safety Monitor Dashboard")

STATIC_DIR = Path(__file__).parent / "static"

# Serve static files (index.html etc.)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Root — serve index.html
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# MJPEG Feed
# ---------------------------------------------------------------------------
@app.get("/feed")
def video_feed():
    def generate():
        while True:
            frame = state.frame_store.get("annotated")
            if frame is None:
                time.sleep(0.033)
                continue
            _, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
            )
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + buf.tobytes()
                + b"\r\n"
            )
            time.sleep(0.033)  # ~30 fps cap

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# REST — Incidents
# ---------------------------------------------------------------------------
def _incident_to_dict(record) -> dict:
    """Convert an IncidentRecord ORM object to a JSON-safe dict."""
    ts = record.timestamp
    if isinstance(ts, datetime):
        ts = ts.isoformat()
    triggered = record.triggered_rules
    if isinstance(triggered, str):
        try:
            triggered = json.loads(triggered)
        except (json.JSONDecodeError, TypeError):
            triggered = [triggered]

    # Derive action_tier from severity_score
    score = float(record.severity_score)
    if score <= 30:
        tier = "silent"
    elif score <= 60:
        tier = "flag"
    else:
        tier = "alert"

    return {
        "id": record.id,
        "timestamp": ts,
        "source_id": record.source_id,
        "severity_score": score,
        "event_type": record.event_type,
        "triggered_rules": triggered,
        "action_tier": tier,
        "snapshot_path": record.snapshot_path,
        "acknowledged": bool(record.acknowledged),
        "false_positive": bool(record.false_positive),
    }


@app.get("/incidents")
async def get_incidents(limit: int = 50, offset: int = 0):
    store = state.data_store_ref.get("store")
    if store is None:
        return JSONResponse(content=[], status_code=200)
    try:
        records = store.get_incidents(limit=limit, offset=offset)
        return [_incident_to_dict(r) for r in records]
    except Exception as exc:
        logger.error("Failed to fetch incidents: %s", exc)
        return JSONResponse(content={"error": str(exc)}, status_code=500)


@app.post("/incidents/{incident_id}/ack")
async def acknowledge_incident(incident_id: str):
    store = state.data_store_ref.get("store")
    if store is None:
        return JSONResponse(content={"error": "store not ready"}, status_code=503)
    try:
        store.acknowledge_incident(incident_id)
        return {"status": "ok", "id": incident_id}
    except Exception as exc:
        logger.error("Failed to ack incident %s: %s", incident_id, exc)
        return JSONResponse(content={"error": str(exc)}, status_code=500)


@app.post("/incidents/{incident_id}/false-positive")
async def mark_false_positive(incident_id: str):
    store = state.data_store_ref.get("store")
    if store is None:
        return JSONResponse(content={"error": "store not ready"}, status_code=503)
    try:
        store.mark_incident_false_positive(incident_id)
        return {"status": "ok", "id": incident_id}
    except Exception as exc:
        logger.error("Failed to mark false positive %s: %s", incident_id, exc)
        return JSONResponse(content={"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# REST — Stats
# ---------------------------------------------------------------------------
@app.get("/stats")
async def get_stats():
    store = state.data_store_ref.get("store")
    if store is None:
        return {"incidents": 0, "near_misses": 0, "alerts": 0}
    try:
        return store.get_stats()
    except Exception as exc:
        logger.error("Failed to fetch stats: %s", exc)
        return JSONResponse(content={"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# REST — Heatmap
# ---------------------------------------------------------------------------
@app.get("/heatmap")
async def get_heatmap():
    store = state.data_store_ref.get("store")
    if store is None:
        return []
    try:
        points = store.get_heatmap_data()
        return [{"x": x, "y": y} for x, y in points]
    except Exception as exc:
        logger.error("Failed to fetch heatmap: %s", exc)
        return JSONResponse(content={"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# WebSocket — Live events
# ---------------------------------------------------------------------------
@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    state.event_queue.get(), timeout=30.0
                )
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
