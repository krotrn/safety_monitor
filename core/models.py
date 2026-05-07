from dataclasses import dataclass
from typing import List, Tuple

import numpy as np


@dataclass
class FrameMetadata:
    frame_id: str
    timestamp: str
    source_id: str
    raw_frame: np.ndarray


@dataclass
class Detection:
    object_id: str
    class_label: str
    confidence: float
    bbox: List[int]
    bbox_norm: List[float]
    track_id: int = -1


@dataclass
class DetectionResult:
    frame_id: str
    timestamp: str
    source_id: str
    detections: List[Detection]


@dataclass
class TrackedDetection:
    object_id: str
    class_label: str
    confidence: float
    bbox: List[int]
    bbox_norm: List[float]
    track_id: int
    center: Tuple[float, float]
    positions: List[Tuple[float, float]]
    velocities: List[float]
    is_stationary: bool
    stationary_duration: float


@dataclass
class TrackedFrame:
    frame_id: str
    timestamp: str
    source_id: str
    raw_frame: np.ndarray
    detections: List[TrackedDetection]


@dataclass
class SeverityResult:
    frame_id: str
    timestamp: str
    source_id: str
    severity_score: float
    event_type: str
    triggered_rules: List[str]
    action_tier: str
    snapshot: np.ndarray
    involved_track_ids: List[int]


@dataclass
class NearMissEvent:
    event_id: str
    timestamp: str
    source_id: str
    track_id_a: int
    track_id_b: int
    class_label_a: str
    class_label_b: str
    min_distance_px: float
    estimated_ttc_seconds: float
    location_norm: Tuple[float, float]
    resolved: bool
