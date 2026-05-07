import argparse
import asyncio
from datetime import datetime
import json
import logging
import threading
import time
from queue import Empty
from typing import Dict, List

import cv2
import numpy as np
import uvicorn
import yaml

from core.camera_manager import CameraManager, FileSource, IPCameraSource, USBCameraSource
from core.alert_manager import AlertManager, TelegramAlertChannel, StubGPIOOutput
from core.data_store import DataStore, IncidentRecord
from core.inference_engine import InferenceEngine
from core.models import SeverityResult, TrackedDetection, TrackedFrame
from core.nearmiss_tracker import NearMissTracker
from core.object_tracker import ObjectTracker
from core.severity_engine import SeverityEngine
from dashboard import state as dashboard_state
from dashboard.main import app as dashboard_app

logger = logging.getLogger(__name__)


def load_config(path: str = "config/settings.yaml") -> Dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception as exc:
        raise RuntimeError(f"Failed to load config from {path}: {exc}") from exc


def build_camera_source(camera_cfg: Dict):
    source_type = camera_cfg["source_type"]
    if source_type == "file":
        resize_to = camera_cfg.get("resize_to")
        return FileSource(
            path=camera_cfg["file_path"],
            target_fps=int(camera_cfg["target_fps"]),
            loop=bool(camera_cfg.get("loop", True)),
            resize_to=tuple(resize_to) if resize_to else None,
        )
    if source_type == "usb":
        return USBCameraSource(
            device_index=int(camera_cfg["device_index"]),
            resolution=tuple(camera_cfg["resolution"]),
        )
    if source_type == "rtsp":
        return IPCameraSource(rtsp_url=camera_cfg["rtsp_url"])
    raise ValueError(f"Unsupported camera source_type: {source_type}")


def format_tracked_line(tracked_frame: TrackedFrame) -> str:
    line = f"{tracked_frame.timestamp} {tracked_frame.source_id}"
    for det in tracked_frame.detections:
        line += f" | {det.class_label}#{det.track_id} {det.confidence:.2f}"
    return line


def format_uptime(elapsed_seconds: float) -> str:
    total_seconds = int(elapsed_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def build_severity_profile(severity_cfg: Dict) -> Dict:
    try:
        rules = severity_cfg["rules"]
        return {
            "person_on_ground_threshold_seconds": rules["PersonStationary"]["duration_seconds"],
            "vehicle_sudden_stop_decel_threshold": rules["SuddenStop"]["velocity_drop_ratio"],
            "person_vehicle_proximity_px": rules["PersonVehicleProximity"]["distance_px"],
            "nighttime_start_hour": rules["Nighttime"]["start_hour"],
            "nighttime_end_hour": rules["Nighttime"]["end_hour"],
            "person_on_ground_aspect_ratio_threshold": rules["PersonOnGround"][
                "aspect_ratio_threshold"
            ],
            "person_on_ground_alt_aspect_ratio": rules["PersonOnGround"].get(
                "alt_aspect_ratio_threshold", 1.0
            ),
            "person_on_ground_alt_stationary_seconds": rules["PersonOnGround"].get(
                "alt_stationary_seconds", 4
            ),
            "near_miss_proximity_px": rules.get("near_miss_proximity_px", 80.0),
            "near_miss_ttc_threshold_seconds": rules.get("near_miss_ttc_threshold_seconds", 1.5),
            "near_miss_min_frames": rules.get("near_miss_min_frames", 2),
        }
    except Exception as exc:
        raise RuntimeError(f"Failed to build severity profile: {exc}") from exc


# ---------------------------------------------------------------------------
# Frame annotation — draw bounding boxes + severity overlay
class IncidentDeduplicator:
    def __init__(self, cooldown_seconds: int = 30):
        self.cooldown_seconds = cooldown_seconds
        self._last_incident: Dict[str, float] = {}

    def check_and_record(self, source_id: str, event_type: str, action_tier: str) -> bool:
        key = f"{source_id}:{event_type}:{action_tier}"
        now = time.time()
        if now - self._last_incident.get(key, 0.0) < self.cooldown_seconds:
            return False
        self._last_incident[key] = now
        return True

_TIER_COLORS = {
    "silent": (100, 100, 100),   # grey
    "flag": (0, 180, 255),       # orange (BGR)
    "alert": (0, 0, 255),        # red (BGR)
}


def annotate_frame(
    frame: np.ndarray,
    detections: List[TrackedDetection],
    severity_score: float,
    action_tier: str,
) -> np.ndarray:
    """Draw bounding boxes and severity overlay on a copy of the frame."""
    annotated = frame.copy()
    color = _TIER_COLORS.get(action_tier, (0, 255, 0))
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"{det.class_label}#{det.track_id}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(
            annotated, label, (x1 + 2, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
        )
    if severity_score > 30:
        text = f"Severity: {int(round(severity_score))} [{action_tier.upper()}]"
        cv2.putText(
            annotated, text, (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA,
        )
    return annotated


def _push_event_nowait(severity: SeverityResult) -> None:
    """Push severity event dict to the async event_queue (thread-safe)."""
    event = {
        "frame_id": severity.frame_id,
        "timestamp": severity.timestamp,
        "source_id": severity.source_id,
        "severity_score": severity.severity_score,
        "event_type": severity.event_type,
        "triggered_rules": severity.triggered_rules,
        "action_tier": severity.action_tier,
    }
    try:
        dashboard_state.event_queue.put_nowait(event)
    except asyncio.QueueFull:
        pass  # drop oldest — dashboard is non-critical


def main() -> None:
    config = load_config()
    camera_cfg = config["camera"]
    inference_cfg = config["inference"]
    severity_cfg = config["severity"]
    storage_cfg = config["storage"]
    runtime_cfg = config.get("runtime") or {}
    uptime_interval = runtime_cfg.get("uptime_log_interval_seconds")
    if uptime_interval is None:
        raise KeyError("runtime.uptime_log_interval_seconds must be set in config")
    alert_threshold = 61.0
    tiers_cfg = severity_cfg.get("tiers")
    if isinstance(tiers_cfg, dict):
        alert_range = tiers_cfg.get("alert")
        if isinstance(alert_range, (list, tuple)) and alert_range:
            alert_threshold = float(alert_range[0])

    engine = InferenceEngine(inference_cfg)
    tracker_cfg = config["tracker"]
    tracker_config = {
        "target_fps": camera_cfg["target_fps"],
        "history_window_seconds": tracker_cfg.get("history_window_seconds")
        or tracker_cfg.get("window_seconds"),
        "stationary_velocity_threshold": tracker_cfg.get("stationary_velocity_threshold")
        or tracker_cfg.get("stationary_velocity_px"),
    }
    if tracker_config["history_window_seconds"] is None:
        raise KeyError("tracker.history_window_seconds or tracker.window_seconds must be set")
    if tracker_config["stationary_velocity_threshold"] is None:
        raise KeyError(
            "tracker.stationary_velocity_threshold or tracker.stationary_velocity_px must be set"
        )
    if "stale_track_timeout_seconds" in tracker_cfg:
        tracker_config["stale_track_timeout_seconds"] = tracker_cfg["stale_track_timeout_seconds"]
    tracker = ObjectTracker(tracker_config)
    severity_profile = build_severity_profile(severity_cfg)
    severity_engine = SeverityEngine(severity_profile)
    store = DataStore(storage_cfg["db_path"], storage_cfg["snapshot_path"])
    nearmiss_tracker = NearMissTracker(severity_profile, store)
    cfg = config
    channels = [StubGPIOOutput()]
    if cfg["alerts"].get("telegram_token"):
        channels.append(
            TelegramAlertChannel(
                token=cfg["alerts"]["telegram_token"],
                chat_id=cfg["alerts"]["telegram_chat_id"],
            )
        )
    alert_manager = AlertManager(
        store,
        channels=channels,
        cooldown_seconds=cfg["alerts"]["cooldown_seconds"],
    )
    incident_deduplicator = IncidentDeduplicator(cooldown_seconds=cfg["alerts"]["cooldown_seconds"])

    # ── Dashboard startup ──
    dashboard_cfg = config.get("dashboard", {})
    dashboard_state.data_store_ref["store"] = store
    dash_host = dashboard_cfg.get("host", "0.0.0.0")
    dash_port = int(dashboard_cfg.get("port", 8000))
    dash_thread = threading.Thread(
        target=uvicorn.run,
        args=(dashboard_app,),
        kwargs={"host": dash_host, "port": dash_port, "log_level": "warning"},
        daemon=True,
    )
    dash_thread.start()
    logger.info("Dashboard started at http://%s:%d", dash_host, dash_port)

    source = build_camera_source(camera_cfg)
    buffer_size = camera_cfg.get("buffer_size") or camera_cfg.get("buffer_maxsize")
    if buffer_size is None:
        raise KeyError("camera.buffer_size or camera.buffer_maxsize must be set in config")
    manager = CameraManager(
        source=source,
        source_id=camera_cfg["source_id"],
        buffer_size=int(buffer_size),
        frame_skip=int(camera_cfg.get("frame_skip", 1)),
        target_fps=int(camera_cfg.get("target_fps", 15)),
    )
    manager.start()
    start_time = time.monotonic()
    last_uptime_log = start_time
    frame_count = 0
    last_severity_score = 0.0
    last_severity_tier = "silent"
    last_severity_event = "none"
    try:
        while True:
            now = time.monotonic()
            if now - last_uptime_log >= float(uptime_interval):
                logger.info("Uptime %s", format_uptime(now - start_time))
                last_uptime_log = now
            try:
                frame_meta = manager.get_frame(timeout=1.0)
            except Empty:
                if not source.is_open:
                    logger.info("Video source finished — processed %d frames.", frame_count)
                    break
                continue
            result = engine.detect(frame_meta)
            tracked = tracker.update(result, frame_meta.raw_frame)
            if tracked.detections:
                logger.info(format_tracked_line(tracked))
                
            nearmiss_events = nearmiss_tracker.process(tracked)
            for nm in nearmiss_events:
                logger.info("nearmiss | %s & %s distance=%.1fpx TTC=%.1fs",
                    nm.class_label_a, nm.class_label_b, nm.min_distance_px, nm.estimated_ttc_seconds)

            severity = severity_engine.score(tracked)
            frame_count += 1
            last_severity_score = severity.severity_score
            last_severity_tier = severity.action_tier
            last_severity_event = severity.event_type

            # ── Annotate frame and push to dashboard ──
            annotated = annotate_frame(
                frame_meta.raw_frame,
                tracked.detections,
                severity.severity_score,
                severity.action_tier,
            )
            dashboard_state.frame_store["annotated"] = annotated

            if severity.severity_score > 0:
                logger.debug(
                    "severity | %s score=%d tier=%s",
                    severity.event_type,
                    int(round(severity.severity_score)),
                    severity.action_tier,
                )
                _push_event_nowait(severity)
            if frame_count % 30 == 0:
                logger.info(
                    "severity heartbeat score=%d tier=%s event=%s",
                    int(round(last_severity_score)),
                    last_severity_tier,
                    last_severity_event,
                )
            if severity.action_tier in {"flag", "alert"}:
                if incident_deduplicator.check_and_record(severity.source_id, severity.event_type, severity.action_tier):
                    logger.info(
                        "Severity %.1f (%s) %s",
                        severity.severity_score,
                        severity.action_tier,
                        severity.event_type,
                    )
                    try:
                        snapshot_path = store.snapshot_store.save(severity.frame_id, severity.snapshot)
                        record = IncidentRecord(
                            source_id=severity.source_id,
                            severity_score=severity.severity_score,
                            event_type=severity.event_type,
                            triggered_rules=json.dumps(severity.triggered_rules),
                            snapshot_path=snapshot_path,
                        )
                        incident_id = store.save_incident(record)
                        
                        if severity.severity_score >= 61.0:
                            recent_nearmisses = store.get_near_misses(limit=50)
                            now_dt = datetime.fromisoformat(severity.timestamp)
                            for nm in recent_nearmisses:
                                nm_dt = nm.timestamp.replace(tzinfo=None) if nm.timestamp.tzinfo is None else nm.timestamp
                                if nm.source_id == severity.source_id:
                                    nm_tracks = {int(nm.track_id_a), int(nm.track_id_b)}
                                    if severity.involved_track_ids and nm_tracks.intersection(set(severity.involved_track_ids)):
                                        if (now_dt - nm_dt).total_seconds() <= 2.0:
                                            store.mark_near_miss_unresolved(nm.id)
                            
                            if severity.severity_score >= alert_threshold:
                                alert_manager.dispatch(severity, incident_id)
                    except Exception as exc:
                        logger.error("Failed to save incident for frame %s: %s", severity.frame_id, exc)
    except KeyboardInterrupt:
        logger.info("Uptime %s", format_uptime(time.monotonic() - start_time))
        manager.stop()
        import os
        os._exit(0)
    finally:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Safety Monitor")
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    args = parser.parse_args()
    log_level = getattr(logging, str(args.log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    main()
