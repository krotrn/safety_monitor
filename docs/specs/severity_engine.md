# Spec — severity_engine.py (Layer 4)

**Module:** `core/severity_engine.py`  
**Layer:** 4 — Scoring  
**Input:** `TrackedFrame`  
**Output:** `SeverityResult`  
**Depends on:** `core/models.py`, context profile dict  
**Used by:** `alert_manager.py`, `data_store.py`

---

## Responsibility

Take a `TrackedFrame` and produce a `SeverityResult` with a score from 0–100,
a list of triggered rules, and an action tier.

Every frame produces a `SeverityResult` — even frames with score 0.
Only `action_tier == "alert"` frames trigger downstream actions.

This module contains no I/O, no alerting, no storage. Pure computation.

---

## Scoring Model

### Design Principle

Rules are **additive** — multiple rules fire independently and their scores sum.
Total is capped at 100. The highest-contributing rule becomes `event_type`.

Rules are **data-driven** — defined in config profile, not hardcoded.
Adding a new rule = add YAML entry + add evaluator function. No core logic changes.

### Action Tiers

| Score Range | Tier | Downstream Effect |
|-------------|------|-------------------|
| 0 – 30 | `"silent"` | Logged to DB only |
| 31 – 60 | `"flag"` | Dashboard highlight, no alert |
| 61 – 100 | `"alert"` | Telegram + GPIO trigger |

---

## Rule Table (Campus Profile)

| Rule Name | Trigger Condition | Score | Objects Involved |
|-----------|-------------------|-------|-----------------|
| `PersonOnGround` | Person bbox aspect ratio ≥ 1.5 (lying flat) | +50 | person |
| `PersonStationary` | Person stationary for ≥ `person_on_ground_threshold_seconds` | +20 | person |
| `VehicleCollision` | Two vehicle bboxes overlapping | +60 | car/truck/bus pair |
| `SuddenStop` | Vehicle velocity drops ≥ 60% vs previous 5-frame mean | +30 | car/truck/bus |
| `PersonVehicleProximity` | Person-vehicle bbox center distance < `person_vehicle_proximity_px` | +25 | person + vehicle |
| `Nighttime` | `timestamp` hour between `nighttime_start_hour` and `nighttime_end_hour` | +10 | — (time modifier) |

All thresholds come from the loaded context profile. No magic numbers in code.

---

## Classes

### `RuleResult`

Internal. Not exposed outside module.

```python
from dataclasses import dataclass
from typing import List

@dataclass
class RuleResult:
    rule_name: str
    score: int
    involved_track_ids: List[int]
```

---

### `RuleEvaluator`

```python
class RuleEvaluator:
    def __init__(self, profile: dict):
        self.profile = profile

    def evaluate_all(self, tracked_frame: TrackedFrame) -> List[RuleResult]:
        """Run all rules. Return list of fired RuleResults (empty = nothing triggered)."""
        results = []
        results.extend(self._eval_person_on_ground(tracked_frame))
        results.extend(self._eval_person_stationary(tracked_frame))
        results.extend(self._eval_vehicle_collision(tracked_frame))
        results.extend(self._eval_sudden_stop(tracked_frame))
        results.extend(self._eval_person_vehicle_proximity(tracked_frame))
        results.extend(self._eval_nighttime(tracked_frame))
        return results
```

#### Rule Implementations

**PersonOnGround**
```python
def _eval_person_on_ground(self, frame: TrackedFrame) -> List[RuleResult]:
    results = []
    for det in frame.detections:
        if det.class_label != "person":
            continue
        w = det.bbox[2] - det.bbox[0]
        h = det.bbox[3] - det.bbox[1]
        aspect_ratio = w / (h + 1e-5)
        if aspect_ratio >= 1.5:
            results.append(RuleResult("PersonOnGround", 50, [det.track_id]))
    return results
```

**PersonStationary**
```python
def _eval_person_stationary(self, frame: TrackedFrame) -> List[RuleResult]:
    threshold = self.profile["person_on_ground_threshold_seconds"]
    results = []
    for det in frame.detections:
        if det.class_label == "person" and det.stationary_duration >= threshold:
            results.append(RuleResult("PersonStationary", 20, [det.track_id]))
    return results
```

**VehicleCollision**
```python
def _eval_vehicle_collision(self, frame: TrackedFrame) -> List[RuleResult]:
    vehicle_classes = {"car", "truck", "bus", "motorcycle"}
    vehicles = [d for d in frame.detections if d.class_label in vehicle_classes]
    results = []
    for i in range(len(vehicles)):
        for j in range(i + 1, len(vehicles)):
            if self._boxes_overlap(vehicles[i].bbox, vehicles[j].bbox):
                results.append(RuleResult(
                    "VehicleCollision", 60,
                    [vehicles[i].track_id, vehicles[j].track_id]
                ))
    return results
```

**SuddenStop**
```python
def _eval_sudden_stop(self, frame: TrackedFrame) -> List[RuleResult]:
    threshold = self.profile["vehicle_sudden_stop_decel_threshold"]
    vehicle_classes = {"car", "truck", "bus"}
    results = []
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
```

**PersonVehicleProximity**
```python
def _eval_person_vehicle_proximity(self, frame: TrackedFrame) -> List[RuleResult]:
    threshold = self.profile["person_vehicle_proximity_px"]
    persons = [d for d in frame.detections if d.class_label == "person"]
    vehicles = [d for d in frame.detections if d.class_label in {"car","truck","bus"}]
    results = []
    for p in persons:
        for v in vehicles:
            dist = self._center_distance(p.bbox, v.bbox)
            if dist < threshold:
                results.append(RuleResult("PersonVehicleProximity", 25, [p.track_id, v.track_id]))
    return results
```

**Nighttime**
```python
def _eval_nighttime(self, frame: TrackedFrame) -> List[RuleResult]:
    from datetime import datetime
    hour = datetime.fromisoformat(frame.timestamp).hour
    start = self.profile["nighttime_start_hour"]
    end = self.profile["nighttime_end_hour"]
    is_night = hour >= start or hour < end
    if is_night:
        return [RuleResult("Nighttime", 10, [])]
    return []
```

**Helpers**
```python
@staticmethod
def _boxes_overlap(b1: List[int], b2: List[int]) -> bool:
    return not (b1[2] < b2[0] or b2[2] < b1[0] or b1[3] < b2[1] or b2[3] < b1[1])

@staticmethod
def _center_distance(b1: List[int], b2: List[int]) -> float:
    cx1, cy1 = (b1[0] + b1[2]) / 2, (b1[1] + b1[3]) / 2
    cx2, cy2 = (b2[0] + b2[2]) / 2, (b2[1] + b2[3]) / 2
    return ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
```

---

### `ActionTierMapper`

```python
class ActionTierMapper:
    @staticmethod
    def map(score: float) -> str:
        if score <= 30:
            return "silent"
        elif score <= 60:
            return "flag"
        else:
            return "alert"
```

---

### `SeverityEngine`

```python
class SeverityEngine:
    def __init__(self, profile: dict):
        self.evaluator = RuleEvaluator(profile)

    def score(self, tracked_frame: TrackedFrame) -> SeverityResult:
        rule_results = self.evaluator.evaluate_all(tracked_frame)

        total_score = min(sum(r.score for r in rule_results), 100)
        triggered_rules = [r.rule_name for r in rule_results]
        involved_ids = list({tid for r in rule_results for tid in r.involved_track_ids})
        event_type = triggered_rules[0] if triggered_rules else "none"
        tier = ActionTierMapper.map(total_score)

        return SeverityResult(
            frame_id        = tracked_frame.frame_id,
            timestamp       = tracked_frame.timestamp,
            source_id       = tracked_frame.source_id,
            severity_score  = float(total_score),
            event_type      = event_type,
            triggered_rules = triggered_rules,
            action_tier     = tier,
            snapshot        = tracked_frame.raw_frame,
            involved_track_ids = involved_ids,
        )
```

---

## Config Keys (from Profile)

```yaml
# config/profiles/campus.yaml
rules:
  person_on_ground_threshold_seconds: 4
  vehicle_sudden_stop_decel_threshold: 0.6   # 60% velocity drop
  near_miss_proximity_px: 80
  person_vehicle_proximity_px: 80
  nighttime_start_hour: 21
  nighttime_end_hour: 5
```

---

## Adding a New Rule

1. Add threshold to `config/profiles/campus.yaml`
2. Add `_eval_new_rule()` method to `RuleEvaluator`
3. Call it inside `evaluate_all()`
4. Add test in `tests/test_severity_engine.py`
5. Update this spec doc

No changes to `SeverityEngine`, `ActionTierMapper`, `data_store`, or `alert_manager`.

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| `tracked_frame.detections` is empty | Return `SeverityResult` with score=0, tier="silent" |
| Rule raises exception | Log WARNING for that rule, skip it, continue evaluating others |
| `timestamp` parse fails in Nighttime rule | Log WARNING, skip Nighttime rule only |

---

## Scalability Hook

`RuleEvaluator` is fully profile-driven. Major project adds:
- `road.yaml` profile with different thresholds
- ML classifier replacing `RuleEvaluator` entirely
- `SeverityEngine.score()` interface stays identical — alert_manager and data_store unchanged

---

## Tests — `tests/test_severity_engine.py`

| Test | Assertion |
|------|-----------|
| `test_empty_frame_scores_zero` | Empty `TrackedFrame` → score=0, tier="silent" |
| `test_person_on_ground_scores_50` | Wide-bbox person → PersonOnGround fires, score≥50 |
| `test_person_stationary_adds_20` | Stationary person past threshold → PersonStationary fires |
| `test_combined_score_capped_at_100` | Multiple rules firing → score never exceeds 100 |
| `test_vehicle_collision_scores_60` | Overlapping vehicle bboxes → VehicleCollision fires |
| `test_sudden_stop_scores_30` | Velocity drop ≥ 60% → SuddenStop fires |
| `test_person_vehicle_proximity_scores_25` | Close person+vehicle → PersonVehicleProximity fires |
| `test_nighttime_modifier` | Timestamp in nighttime range → Nighttime fires |
| `test_tier_silent` | Score 0–30 → tier="silent" |
| `test_tier_flag` | Score 31–60 → tier="flag" |
| `test_tier_alert` | Score 61–100 → tier="alert" |
| `test_event_type_is_first_triggered_rule` | `event_type` matches first rule name |
| `test_event_type_none_when_no_rules` | No rules fire → `event_type="none"` |

---

## Done When

- Person lying flat in test video produces `PersonOnGround` rule, score ≥ 50
- Score ≥ 70 when both `PersonOnGround` and `PersonStationary` fire
- `action_tier == "alert"` when score ≥ 61
- Result saved to DB via `data_store.save_incident()`