# Context Profile: Campus

## Purpose
Rule overrides for a college campus deployment — parking lots, walkways, building entrances. Persons are the primary concern; vehicles are present but secondary. False-positive rate must be low (students sitting on grass ≠ incident).

## File
`config/profiles/campus.yaml`

## Profile Config
```yaml
profile: campus
description: "College campus — parking lots, walkways, entrances"

rules:
  # Person on ground: longer threshold than road profile (students sit on grass)
  person_on_ground_threshold_seconds: 6   # road profile would use 3s
  
  # Near-miss proximity — tighter on campus (shared pedestrian/vehicle zones)
  near_miss_proximity_px: 70
  
  # Vehicle sudden stop — lower sensitivity (speed bumps cause false positives)
  vehicle_sudden_stop_decel_threshold: 0.75   # road: 0.6
  
  # Nighttime modifier applies 21:00–05:00
  nighttime_score_modifier: 15   # campus: higher (lower foot traffic = more suspicious)
  
  # Classes to monitor (ignore trucks/buses — not typical on campus)
  classes_of_interest:
    - person
    - car
    - motorcycle
  
  # Classes to ignore entirely
  ignore_classes:
    - truck
    - bus

severity_overrides:
  # PersonVehicleProximity score is lower on campus (students cross parking lots normally)
  PersonVehicleProximity:
    score: 15    # default is 25

# Alert behavior for this context
alert:
  # On campus, flag tier also sends a low-priority Telegram message (no photo)
  flag_telegram_notify: true
  flag_telegram_text_only: true
```

## Rationale for Each Override

| Setting | Campus value | Default | Why |
|--------|-------------|---------|-----|
| person_on_ground_threshold | 6s | 4s | Students rest on grass — avoid false positives |
| near_miss_proximity | 70px | 80px | Narrower walkways, tighter vehicle-pedestrian zones |
| vehicle_decel_threshold | 0.75 | 0.60 | Speed bumps trigger false positives at default |
| nighttime_modifier | 15 | 10 | Nighttime incidents on campus are more anomalous |
| PersonVehicleProximity score | 15 | 25 | Students routinely cross parking lots |

## Adding a New Profile
1. Copy this file to `config/profiles/{new_profile}.yaml`
2. Change `profile:` key in `settings.yaml`
3. No code changes — `ContextProfileLoader` picks it up automatically