from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Tuple

import numpy as np

from core.models import DetectionResult, TrackedDetection, TrackedFrame

logger = logging.getLogger(__name__)


@dataclass
class TrackState:
    track_id: int
    class_label: str
    positions: Deque[Tuple[float, float]]
    velocities: Deque[float]
    last_seen: float
    stationary_velocity_threshold: float = field(repr=False, default=5.0)
    target_fps: float = field(repr=False, default=15.0)

    @property
    def is_stationary(self) -> bool:
        if len(self.velocities) < 10:
            return False
        recent = list(self.velocities)[-10:]
        return (sum(recent) / 10) < self.stationary_velocity_threshold

    @property
    def stationary_duration(self) -> float:
        if len(self.velocities) < 10:
            return 0.0
        count = 0
        for velocity in reversed(self.velocities):
            if velocity < self.stationary_velocity_threshold:
                count += 1
            else:
                break
        if self.target_fps == 0:
            return 0.0
        return count / self.target_fps


class ObjectTracker:
    def __init__(self, config: dict) -> None:
        target_fps = config.get("target_fps")
        if target_fps is None:
            raise KeyError("tracker.target_fps must be provided")
        history_window_seconds = config.get("history_window_seconds", 5)
        stationary_velocity_threshold = config.get("stationary_velocity_threshold", 5.0)
        stale_track_timeout_seconds = config.get("stale_track_timeout_seconds", 2.0)

        self._target_fps = float(target_fps)
        self._history_window_seconds = float(history_window_seconds)
        self._stationary_velocity_threshold = float(stationary_velocity_threshold)
        self._stale_track_timeout_seconds = float(stale_track_timeout_seconds)
        self._history_maxlen = max(1, int(self._target_fps * self._history_window_seconds))
        self._tracks: Dict[int, TrackState] = {}

    def update(self, detection_result: DetectionResult, raw_frame: np.ndarray) -> TrackedFrame:
        if raw_frame is None:
            logger.error("Raw frame is required for tracking")
            raise ValueError("raw_frame must not be None")
        self._purge_stale_tracks()

        tracked_detections: List[TrackedDetection] = []
        for detection in detection_result.detections:
            track_id_value = getattr(detection, "track_id", -1)
            try:
                track_id = int(track_id_value)
            except (TypeError, ValueError):
                track_id = -1
            if track_id == -1:
                continue
            if not detection.bbox or len(detection.bbox) != 4:
                logger.warning("Detection missing bbox for track_id %s", track_id)
                continue
            state = self._get_or_create_state(track_id, detection.class_label)
            center = self._compute_center(detection.bbox)
            if state.positions:
                prev_center = state.positions[-1]
                velocity = math.hypot(center[0] - prev_center[0], center[1] - prev_center[1])
                state.velocities.append(velocity)
            state.positions.append(center)
            state.last_seen = time.time()

            tracked_detections.append(
                TrackedDetection(
                    object_id=detection.object_id,
                    class_label=detection.class_label,
                    confidence=detection.confidence,
                    bbox=detection.bbox,
                    bbox_norm=detection.bbox_norm,
                    track_id=track_id,
                    center=center,
                    positions=list(state.positions),
                    velocities=list(state.velocities),
                    is_stationary=state.is_stationary,
                    stationary_duration=state.stationary_duration,
                )
            )

        return TrackedFrame(
            frame_id=detection_result.frame_id,
            timestamp=detection_result.timestamp,
            source_id=detection_result.source_id,
            raw_frame=raw_frame,
            detections=tracked_detections,
        )

    def _get_or_create_state(self, track_id: int, class_label: str) -> TrackState:
        if track_id in self._tracks:
            state = self._tracks[track_id]
            state.class_label = class_label
            return state
        positions: Deque[Tuple[float, float]] = deque(maxlen=self._history_maxlen)
        velocities: Deque[float] = deque(maxlen=self._history_maxlen)
        state = TrackState(
            track_id=track_id,
            class_label=class_label,
            positions=positions,
            velocities=velocities,
            last_seen=time.time(),
            stationary_velocity_threshold=self._stationary_velocity_threshold,
            target_fps=self._target_fps,
        )
        self._tracks[track_id] = state
        return state

    def _compute_center(self, bbox: List[int]) -> Tuple[float, float]:
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def _purge_stale_tracks(self) -> None:
        now = time.time()
        stale_ids = [
            track_id
            for track_id, state in self._tracks.items()
            if now - state.last_seen > self._stale_track_timeout_seconds
        ]
        for track_id in stale_ids:
            self._tracks.pop(track_id, None)
