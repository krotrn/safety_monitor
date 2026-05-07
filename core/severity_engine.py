from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List

from core.models import SeverityResult, TrackedFrame

logger = logging.getLogger(__name__)


@dataclass
class RuleResult:
    rule_name: str
    score: int
    involved_track_ids: List[int]


class RuleEvaluator:
    def __init__(self, profile: dict):
        self.profile = profile

    def evaluate_all(self, tracked_frame: TrackedFrame) -> List[RuleResult]:
        results: List[RuleResult] = []
        results.extend(self._safe_eval(self._eval_person_on_ground, "PersonOnGround", tracked_frame))
        results.extend(
            self._safe_eval(self._eval_person_stationary, "PersonStationary", tracked_frame)
        )
        results.extend(
            self._safe_eval(self._eval_vehicle_collision, "VehicleCollision", tracked_frame)
        )
        results.extend(self._safe_eval(self._eval_sudden_stop, "SuddenStop", tracked_frame))
        results.extend(
            self._safe_eval(
                self._eval_person_vehicle_proximity,
                "PersonVehicleProximity",
                tracked_frame,
            )
        )
        results.extend(self._safe_eval(self._eval_nighttime, "Nighttime", tracked_frame))
        return results

    def _safe_eval(self, fn, rule_name: str, tracked_frame: TrackedFrame) -> List[RuleResult]:
        try:
            return fn(tracked_frame)
        except Exception as exc:
            logger.warning("Rule %s failed: %s", rule_name, exc)
            return []

    def _eval_person_on_ground(self, frame: TrackedFrame) -> List[RuleResult]:
        threshold = float(self.profile.get("person_on_ground_aspect_ratio_threshold", 1.5))
        alt_threshold = float(self.profile.get("person_on_ground_alt_aspect_ratio", 1.0))
        alt_seconds = float(self.profile.get("person_on_ground_alt_stationary_seconds", 4))
        results: List[RuleResult] = []
        for det in frame.detections:
            if det.class_label != "person":
                continue
            w = det.bbox[2] - det.bbox[0]
            h = det.bbox[3] - det.bbox[1]
            aspect_ratio = w / (h + 1e-5)
            logger.debug(
                "person track_id=%d bbox=%s w=%d h=%d aspect_ratio=%.2f threshold=%.2f"
                " stationary=%.1fs",
                det.track_id, det.bbox, w, h, aspect_ratio, threshold,
                det.stationary_duration,
            )
            # Condition 1: clearly lying flat (top-down or extreme side angle)
            if aspect_ratio >= threshold:
                results.append(RuleResult("PersonOnGround", 50, [det.track_id]))
            # Condition 2: wider-than-standing bbox + confirmed stationary
            elif aspect_ratio >= alt_threshold and det.stationary_duration >= alt_seconds:
                logger.debug(
                    "PersonOnGround alt trigger: aspect_ratio=%.2f >= %.2f AND"
                    " stationary=%.1fs >= %.1fs",
                    aspect_ratio, alt_threshold, det.stationary_duration, alt_seconds,
                )
                results.append(RuleResult("PersonOnGround", 50, [det.track_id]))
        return results

    def _eval_person_stationary(self, frame: TrackedFrame) -> List[RuleResult]:
        threshold = float(self.profile["person_on_ground_threshold_seconds"])
        results: List[RuleResult] = []
        for det in frame.detections:
            if det.class_label == "person" and det.stationary_duration >= threshold:
                results.append(RuleResult("PersonStationary", 20, [det.track_id]))
        return results

    def _eval_vehicle_collision(self, frame: TrackedFrame) -> List[RuleResult]:
        vehicle_classes = {"car", "truck", "bus", "motorcycle"}
        vehicles = [d for d in frame.detections if d.class_label in vehicle_classes]
        results: List[RuleResult] = []
        for i in range(len(vehicles)):
            for j in range(i + 1, len(vehicles)):
                if self._boxes_overlap(vehicles[i].bbox, vehicles[j].bbox):
                    results.append(
                        RuleResult(
                            "VehicleCollision",
                            60,
                            [vehicles[i].track_id, vehicles[j].track_id],
                        )
                    )
        return results

    def _eval_sudden_stop(self, frame: TrackedFrame) -> List[RuleResult]:
        threshold = float(self.profile["vehicle_sudden_stop_decel_threshold"])
        vehicle_classes = {"car", "truck", "bus"}
        results: List[RuleResult] = []
        for det in frame.detections:
            if det.class_label not in vehicle_classes:
                continue
            if len(det.velocities) < 6:
                continue
            recent = det.velocities[-1]
            prev_mean = sum(det.velocities[-6:-1]) / 5
            if prev_mean > 0 and (prev_mean - recent) / prev_mean >= threshold:
                results.append(RuleResult("SuddenStop", 30, [det.track_id]))
        return results

    def _eval_person_vehicle_proximity(self, frame: TrackedFrame) -> List[RuleResult]:
        threshold = float(self.profile["person_vehicle_proximity_px"])
        persons = [d for d in frame.detections if d.class_label == "person"]
        vehicles = [d for d in frame.detections if d.class_label in {"car", "truck", "bus"}]
        results: List[RuleResult] = []
        for person in persons:
            for vehicle in vehicles:
                dist = self._center_distance(person.bbox, vehicle.bbox)
                if dist < threshold:
                    results.append(
                        RuleResult(
                            "PersonVehicleProximity",
                            25,
                            [person.track_id, vehicle.track_id],
                        )
                    )
        return results

    def _eval_nighttime(self, frame: TrackedFrame) -> List[RuleResult]:
        try:
            hour = datetime.fromisoformat(frame.timestamp).hour
        except Exception as exc:
            logger.warning("Nighttime rule skipped: %s", exc)
            return []
        start = int(self.profile["nighttime_start_hour"])
        end = int(self.profile["nighttime_end_hour"])
        is_night = hour >= start or hour < end
        if is_night:
            return [RuleResult("Nighttime", 10, [])]
        return []

    @staticmethod
    def _boxes_overlap(b1: List[int], b2: List[int]) -> bool:
        return not (b1[2] < b2[0] or b2[2] < b1[0] or b1[3] < b2[1] or b2[3] < b1[1])

    @staticmethod
    def _center_distance(b1: List[int], b2: List[int]) -> float:
        cx1, cy1 = (b1[0] + b1[2]) / 2, (b1[1] + b1[3]) / 2
        cx2, cy2 = (b2[0] + b2[2]) / 2, (b2[1] + b2[3]) / 2
        return ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5


class ActionTierMapper:
    @staticmethod
    def map(score: float) -> str:
        if score <= 30:
            return "silent"
        if score <= 60:
            return "flag"
        return "alert"


class SeverityEngine:
    def __init__(self, profile: dict):
        self.evaluator = RuleEvaluator(profile)

    def score(self, tracked_frame: TrackedFrame) -> SeverityResult:
        if not tracked_frame.detections:
            return SeverityResult(
                frame_id=tracked_frame.frame_id,
                timestamp=tracked_frame.timestamp,
                source_id=tracked_frame.source_id,
                severity_score=0.0,
                event_type="none",
                triggered_rules=[],
                action_tier="silent",
                snapshot=tracked_frame.raw_frame,
                involved_track_ids=[],
            )
        rule_results = self.evaluator.evaluate_all(tracked_frame)
        total_score = min(sum(result.score for result in rule_results), 100)
        triggered_rules = [result.rule_name for result in rule_results]
        involved_ids = list({tid for result in rule_results for tid in result.involved_track_ids})
        event_type = triggered_rules[0] if triggered_rules else "none"
        tier = ActionTierMapper.map(total_score)

        return SeverityResult(
            frame_id=tracked_frame.frame_id,
            timestamp=tracked_frame.timestamp,
            source_id=tracked_frame.source_id,
            severity_score=float(total_score),
            event_type=event_type,
            triggered_rules=triggered_rules,
            action_tier=tier,
            snapshot=tracked_frame.raw_frame,
            involved_track_ids=involved_ids,
        )
