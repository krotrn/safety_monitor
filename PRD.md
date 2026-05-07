# PRD — Single-Node Safety Monitor (Minor Project)

**Version:** 1.0  
**Status:** Draft  
**Author:** SafeGrid Team  
**Last Updated:** 2026-05-06

---

## 1. Problem Statement

Accidents and safety incidents on campuses, parking lots, and institutional premises go undetected or are reported too late for effective response. Existing CCTV systems are passive — they record but do not act. Security personnel cannot monitor all feeds simultaneously. By the time a human notices an incident, the response window has already closed.

This project builds an active, intelligent safety monitor that watches a live camera feed, detects incidents and near-misses in real time, scores their severity, and triggers proportional responses automatically — without requiring a human to be watching.

---

## 2. Goals

| Goal | Description |
|------|-------------|
| **G1** | Detect safety incidents from a live camera feed with no human in the loop |
| **G2** | Score severity on a 0–100 scale, not just binary detection |
| **G3** | Alert the right people at the right threshold, not on every detection |
| **G4** | Log near-misses, not just confirmed incidents |
| **G5** | Prove the full end-to-end loop works on edge hardware |

---

## 3. Non-Goals (Minor Project Scope)

The following are explicitly out of scope for the minor project:

- Multi-camera support (single camera only)
- Cloud sync or remote deployment
- Mobile app
- PPE detection
- Custom model training
- Multi-tenant or SaaS features
- Road or factory context profiles (campus only)
- LLM-based incident summarization

These are tracked for the major project.

---

## 4. Target Users

### Primary
**Campus Security Officer**  
Monitors the dashboard during shift. Receives Telegram alerts when severity is critical. Can mark false positives from the dashboard.

### Secondary
**Campus Safety Administrator**  
Reviews weekly incident logs and near-miss heatmaps. Uses data to identify high-risk zones and improve campus layout or protocols.

### System Actor
**The Monitor Itself**  
Operates autonomously 24/7. Detects, scores, alerts, and logs without human intervention.

---

## 5. Deployment Context

**Profile: Campus**

| Parameter | Value |
|-----------|-------|
| Environment | Outdoor campus / parking lot / corridor |
| Camera type | USB webcam or IP camera (single) |
| Edge device | Raspberry Pi 5 or NVIDIA Jetson Nano |
| Network | Local Wi-Fi or LAN |
| Alert channels | Telegram bot + GPIO buzzer |
| Dashboard access | Local network browser |

---

## 6. Core Features

### F1 — Live Incident Detection
- Ingest live camera feed at 10–15 FPS
- Run YOLOv8 (nano/small) inference on each frame
- Detect: person, vehicle, fall (person on ground), sudden stop
- Output structured detection result per frame with bounding boxes and confidence scores

**Acceptance Criteria:**
- [ ] System detects a person lying on the ground within 3 seconds of the event
- [ ] Confidence score ≥ 0.5 for valid detections
- [ ] False trigger rate on empty frames < 5%

---

### F2 — Severity Scoring (0–100)
- Every detected frame produces a severity score
- Score is additive across triggered rules (see Rule Table below)
- Score is capped at 100
- Three action tiers mapped to score ranges

**Rule Table:**

| Rule | Trigger Condition | Score |
|------|-------------------|-------|
| PersonOnGround | Person bbox aspect ratio > 1.5 (lying flat) | +50 |
| PersonStationary | Person not moved for > 4 seconds | +20 |
| VehicleCollision | Two vehicle bboxes overlapping | +60 |
| SuddenStop | Vehicle velocity drops > 60% in 1 second | +30 |
| PersonVehicleProximity | Person + vehicle distance < 80px | +25 |
| Nighttime | Timestamp between 21:00–05:00 | +10 |

**Action Tiers:**

| Score | Tier | Response |
|-------|------|----------|
| 0–30 | Silent | Log only |
| 31–60 | Flag | Dashboard highlight |
| 61–100 | Alert | Telegram + GPIO trigger |

**Acceptance Criteria:**
- [ ] Person lying down in test video scores ≥ 70
- [ ] Empty frame or person walking scores < 20
- [ ] Tier mapping fires correct downstream action every time

---

### F3 — Near-Miss Tracking
- Trajectories of all tracked objects maintained over a 5-second rolling window
- Flags events where two objects came close but no incident occurred
- Near-miss events written to database with normalized location coordinates
- Heatmap accumulates over time and survives restarts

**Near-Miss Trigger Conditions:**
- Two tracked objects within 80px of each other for ≥ 2 frames
- OR estimated time-to-collision < 1.5 seconds based on current velocities

**Acceptance Criteria:**
- [ ] Near-miss event logged when two objects pass within threshold distance
- [ ] Heatmap shows correct spatial clustering after 10+ events
- [ ] Near-miss events do not trigger full alert (logged silently unless severity also fires)

---

### F4 — Alert & Response
- Telegram bot sends photo + severity score + event type + timestamp on Alert tier
- GPIO relay triggers buzzer for Alert tier events
- Deduplication: same event type from same camera suppressed for 30 seconds after alert
- All alerts logged with channel, timestamp, acknowledged status

**Acceptance Criteria:**
- [ ] Telegram message received within 5 seconds of incident detection
- [ ] Message includes: frame snapshot, score, event type, timestamp, camera ID
- [ ] Duplicate alerts suppressed within cooldown window
- [ ] GPIO output triggers physical buzzer on Alert tier

---

### F5 — Incident Logging
- Every detected event stored in SQLite with full metadata
- Frame snapshots saved as JPEG to local disk, referenced by incident record
- Raw frame records pruned after 24 hours; incident records kept permanently
- False-positive flag writeable from dashboard

**Acceptance Criteria:**
- [ ] Incident record queryable within 1 second of event
- [ ] Snapshot file exists at referenced path for every incident
- [ ] False-positive flag persists across system restarts

---

### F6 — Live Dashboard
- Browser-accessible local web UI
- Live annotated MJPEG feed (bounding boxes + labels + score overlay)
- Incident table: timestamp, event type, severity score, snapshot thumbnail, false-positive button
- Near-miss heatmap: canvas overlay on reference frame
- Severity distribution chart: last 1 hour, bar chart
- WebSocket push for new incidents (no polling)

**Acceptance Criteria:**
- [ ] Live feed visible in browser within 3 seconds of system start
- [ ] New incident appears in table within 2 seconds of detection
- [ ] False-positive button updates DB and removes dashboard flag
- [ ] Heatmap renders with correct spatial distribution

---

## 7. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Detection latency | < 2 seconds from event to detection |
| Alert latency | < 5 seconds from detection to Telegram delivery |
| Frame throughput | ≥ 10 FPS sustained on edge device |
| Uptime | Runs unattended for 8+ hours without crash |
| Disk usage | Bounded — raw frames auto-pruned after 24h |
| Restart recovery | All DB records and heatmap intact after reboot |
| Dashboard load | Live feed renders in < 3 seconds on local network |

---

## 8. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US1 | Security officer | receive a Telegram alert with photo when someone falls | I can respond immediately without watching the screen |
| US2 | Security officer | see a live annotated feed in my browser | I can monitor the area remotely from my desk |
| US3 | Security officer | mark an alert as a false positive | the system learns what not to flag and I can clear noise |
| US4 | Safety admin | view a log of all incidents from the past week | I can report on safety performance |
| US5 | Safety admin | see a heatmap of near-miss locations | I can identify high-risk zones before accidents happen |
| US6 | Safety admin | filter incidents by severity tier | I can focus review on critical events only |
| US7 | System | detect a person lying on the ground without being told explicitly | I can flag incidents that weren't pre-programmed |
| US8 | System | suppress duplicate alerts for the same ongoing event | I don't flood the security officer's phone |

---

## 9. System Constraints

| Constraint | Detail |
|------------|--------|
| Hardware budget | Request Jetson Nano or Raspberry Pi 5 — no cloud GPU |
| Inference | Must run fully on-device — no cloud API for detection |
| Connectivity | Works on local network only — no internet dependency for core function |
| Camera | Single USB or IP camera for minor project |
| Model | YOLOv8 nano or small — must run at ≥ 10 FPS on chosen hardware |
| Storage | SQLite only — no external database for minor project |
| Alert | Telegram Bot API (free) — Twilio SMS optional |

---

## 10. Success Metrics

The minor project is considered complete and successful when:

- [ ] End-to-end loop works: camera → detection → scoring → alert → dashboard → log
- [ ] Person-on-ground scenario triggers Alert tier and delivers Telegram message with snapshot
- [ ] Near-miss event is logged and appears on heatmap after two objects pass within threshold
- [ ] System runs unattended for a full demo session (≥ 30 minutes) without crash
- [ ] False-positive workflow completes: alert fires → officer marks false positive → flagged in DB
- [ ] Dashboard shows live feed, incident table, and heatmap simultaneously

---

## 11. Milestones

| Phase | Deliverable | Done When |
|-------|-------------|-----------|
| Phase 0 | Project setup, folder structure, config | `main.py` runs without error |
| Phase 1 | Camera + Inference | Detections print to console from video file |
| Phase 2 | Object Tracker | Same person keeps same ID across 50+ frames |
| Phase 3 | Storage | Fake incident written and queried from DB |
| Phase 4 | Severity Engine | Person-on-ground scores ≥ 70, saved to DB |
| Phase 5 | Alert Manager | Telegram receives photo on Alert tier event |
| Phase 6 | Dashboard | Browser shows live feed + incident table |
| Phase 7 | Near-Miss + GPIO | Heatmap populates, buzzer triggers on hardware |

---

## 12. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| OQ1 | Jetson Nano vs Raspberry Pi 5 — which hardware gets approved? | Team | Open |
| OQ2 | Where on campus will the camera be physically placed for demo? | Team | Open |
| OQ3 | Will Telegram bot be approved for institutional network? | Team | Open |
| OQ4 | Is GPIO buzzer acceptable for the demo environment? | Team | Open |

---

*This PRD covers the minor project only. Major project PRD (multi-node, cloud sync, mobile app, retraining pipeline) to be written after minor project demo.*