import uuid
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from core.data_store import NearMissRecord
from core.models import TrackedDetection, TrackedFrame, NearMissEvent

logger = logging.getLogger(__name__)

@dataclass
class NearMissCandidate:
    track_id_a: int
    track_id_b: int
    class_label_a: str
    class_label_b: str
    min_distance_px: float
    estimated_ttc_seconds: float
    location_norm: Tuple[float, float]
    frame_count: int


class TrajectoryAnalyzer:
    def __init__(self, profile: dict):
        self.proximity_threshold = profile["near_miss_proximity_px"]
        self.ttc_threshold = profile.get("near_miss_ttc_threshold_seconds", 1.5)
        self.min_frames = profile.get("near_miss_min_frames", 2)

    def _check_proximity(self, a: TrackedDetection, b: TrackedDetection) -> Optional[float]:
        cx_a, cy_a = a.center
        cx_b, cy_b = b.center
        dist = ((cx_a - cx_b)**2 + (cy_a - cy_b)**2) ** 0.5
        if dist < self.proximity_threshold:
            return dist
        return None

    def _estimate_ttc(self, a: TrackedDetection, b: TrackedDetection) -> float:
        if len(a.positions) < 2 or len(b.positions) < 2:
            return -1.0

        def avg_velocity_vector(det: TrackedDetection) -> Tuple[float, float]:
            positions = det.positions[-4:]
            if len(positions) < 2:
                return (0.0, 0.0)
            dx = positions[-1][0] - positions[0][0]
            dy = positions[-1][1] - positions[0][1]
            n = len(positions) - 1
            return (dx / n, dy / n)

        vax, vay = avg_velocity_vector(a)
        vbx, vby = avg_velocity_vector(b)

        rvx = vax - vbx
        rvy = vay - vby

        ax, ay = a.center
        bx, by = b.center

        rpx = ax - bx
        rpy = ay - by

        dot = rpx * rvx + rpy * rvy
        if dot >= 0:
            return -1.0

        rel_pos_sq = rpx**2 + rpy**2
        if dot == 0:
            return -1.0
        ttc_frames = -rel_pos_sq / dot
        ttc_seconds = ttc_frames / 15.0

        return ttc_seconds if ttc_seconds > 0 else -1.0

    def analyze(self, tracked_frame: TrackedFrame) -> List[NearMissCandidate]:
        candidates = []
        dets = tracked_frame.detections
        n = len(dets)
        if n < 2:
            return candidates

        for i in range(n):
            for j in range(i + 1, n):
                a = dets[i]
                b = dets[j]

                dist = self._check_proximity(a, b)
                ttc = -1.0
                try:
                    ttc = self._estimate_ttc(a, b)
                except Exception as exc:
                    logger.warning("TTC calculation failed: %s", exc)

                if dist is not None or (0 < ttc < self.ttc_threshold):
                    cx_a, cy_a = a.center
                    cx_b, cy_b = b.center
                    h, w = tracked_frame.raw_frame.shape[:2]
                    mid_x = (cx_a + cx_b) / 2.0 / w if w > 0 else 0.5
                    mid_y = (cy_a + cy_b) / 2.0 / h if h > 0 else 0.5
                    
                    dist_val = dist if dist is not None else float("inf")
                    
                    candidates.append(
                        NearMissCandidate(
                            track_id_a=a.track_id,
                            track_id_b=b.track_id,
                            class_label_a=a.class_label,
                            class_label_b=b.class_label,
                            min_distance_px=dist_val,
                            estimated_ttc_seconds=ttc,
                            location_norm=(mid_x, mid_y),
                            frame_count=0,
                        )
                    )
        return candidates


class NearMissBuffer:
    def __init__(self, min_frames: int = 2):
        self._counts: Dict[Tuple[int, int], int] = {}
        self.min_frames = min_frames

    def update(self, pair: Tuple[int, int]) -> int:
        self._counts[pair] = self._counts.get(pair, 0) + 1
        return self._counts[pair]

    def reset(self, pair: Tuple[int, int]) -> None:
        self._counts.pop(pair, None)

    def should_emit(self, pair: Tuple[int, int]) -> bool:
        return self._counts.get(pair, 0) == self.min_frames

    def cleanup(self, active_pairs: set) -> None:
        stale = [k for k in self._counts if k not in active_pairs]
        for k in stale:
            del self._counts[k]


class HeatmapAccumulator:
    def __init__(self, grid_size: int = 20):
        self.grid_size = grid_size
        self._grid: List[List[int]] = [[0] * grid_size for _ in range(grid_size)]

    def record(self, location_norm: Tuple[float, float]) -> None:
        x, y = location_norm
        col = min(int(x * self.grid_size), self.grid_size - 1)
        row = min(int(y * self.grid_size), self.grid_size - 1)
        self._grid[row][col] += 1

    def get_grid(self) -> List[List[int]]:
        return self._grid

    def to_points(self) -> List[dict]:
        points = []
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                if self._grid[r][c] > 0:
                    points.append({
                        "x": (c + 0.5) / self.grid_size,
                        "y": (r + 0.5) / self.grid_size,
                        "weight": self._grid[r][c]
                    })
        return points


class NearMissTracker:
    def __init__(self, profile: dict, data_store):
        self.analyzer = TrajectoryAnalyzer(profile)
        self.buffer = NearMissBuffer(
            min_frames=profile.get("near_miss_min_frames", 2)
        )
        self.heatmap = HeatmapAccumulator(grid_size=20)
        self.store = data_store

    def process(self, tracked_frame: TrackedFrame) -> List[NearMissEvent]:
        candidates = self.analyzer.analyze(tracked_frame)
        active_pairs = {
            (min(c.track_id_a, c.track_id_b), max(c.track_id_a, c.track_id_b))
            for c in candidates
        }

        emitted = []
        for candidate in candidates:
            pair = (
                min(candidate.track_id_a, candidate.track_id_b),
                max(candidate.track_id_a, candidate.track_id_b),
            )
            self.buffer.update(pair)
            if self.buffer.should_emit(pair):
                event = self._build_event(tracked_frame, candidate)
                try:
                    db_record = NearMissRecord(
                        id=event.event_id,
                        source_id=event.source_id,
                        track_id_a=str(event.track_id_a),
                        track_id_b=str(event.track_id_b),
                        class_label_a=event.class_label_a,
                        class_label_b=event.class_label_b,
                        min_distance_px=event.min_distance_px,
                        estimated_ttc_seconds=event.estimated_ttc_seconds,
                        location_x=event.location_norm[0],
                        location_y=event.location_norm[1],
                        resolved=event.resolved,
                    )
                    self.store.save_near_miss(db_record)
                except Exception as exc:
                    logger.error("Failed to save near miss: %s", exc)
                self.heatmap.record(candidate.location_norm)
                emitted.append(event)

        self.buffer.cleanup(active_pairs)
        return emitted

    def _build_event(self, frame: TrackedFrame, c: NearMissCandidate) -> NearMissEvent:
        return NearMissEvent(
            event_id=str(uuid.uuid4()),
            timestamp=frame.timestamp,
            source_id=frame.source_id,
            track_id_a=c.track_id_a,
            track_id_b=c.track_id_b,
            class_label_a=c.class_label_a,
            class_label_b=c.class_label_b,
            min_distance_px=c.min_distance_px,
            estimated_ttc_seconds=c.estimated_ttc_seconds,
            location_norm=c.location_norm,
            resolved=True,
        )

    def get_heatmap_points(self) -> List[dict]:
        return self.heatmap.to_points()
