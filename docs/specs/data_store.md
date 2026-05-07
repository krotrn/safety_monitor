# Module Spec: data_store

## Purpose
Single persistence layer for the entire system. Owns SQLite schema, snapshot file storage, and a retention manager that keeps disk usage bounded. All other modules call data_store — nothing else touches the DB directly.

## Location
`core/data_store.py`

## Responsibilities
- Initialize and migrate SQLite schema on startup
- Save/query IncidentRecord, NearMissRecord, AlertRecord
- Save JPEG frame snapshots to disk; incidents reference by frame_id, not binary blob
- Delete raw frame rows older than 24h (incidents + alerts kept forever)
- Expose typed query methods — no raw SQL outside this module

## Schema: 4 Tables

### incidents
| Column          | Type     | Notes                              |
|-----------------|----------|------------------------------------|
| id              | TEXT PK  | uuid4                              |
| timestamp       | DATETIME |                                    |
| source_id       | TEXT     | "cam_01"                           |
| severity_score  | REAL     | 0.0–100.0                          |
| event_type      | TEXT     | "PersonOnGround"                   |
| triggered_rules | TEXT     | JSON array string                  |
| snapshot_path   | TEXT     | relative path under snapshot_root  |
| acknowledged    | BOOLEAN  | default False                      |
| false_positive  | BOOLEAN  | default False                      |
| acknowledged_at | DATETIME | nullable                           |

### near_misses
| Column         | Type     | Notes             |
|----------------|----------|-------------------|
| id             | TEXT PK  | uuid4             |
| timestamp      | DATETIME |                   |
| source_id      | TEXT     |                   |
| location_x     | REAL     | 0.0–1.0 normalized|
| location_y     | REAL     | 0.0–1.0 normalized|
| min_distance_px| REAL     |                   |
| object_classes | TEXT     | JSON: ["person","car"] |

### alerts
| Column              | Type     | Notes              |
|---------------------|----------|--------------------|
| id                  | TEXT PK  | uuid4              |
| severity_result_id  | TEXT     | FK → incidents.id  |
| timestamp           | DATETIME |                    |
| source_id           | TEXT     |                    |
| channels_triggered  | TEXT     | JSON array         |
| acknowledged        | BOOLEAN  | default False      |
| false_positive      | BOOLEAN  | default False      |
| acknowledged_at     | DATETIME | nullable           |

### frames (pruned)
| Column     | Type     | Notes                     |
|------------|----------|---------------------------|
| id         | TEXT PK  | frame_id uuid             |
| timestamp  | DATETIME |                           |
| source_id  | TEXT     |                           |
| detection_count | INT |                           |

Raw frame rows pruned after 24h. Snapshot JPEGs retained as long as the incident record exists.

## Internal Components

### DataStore (main class)
```python
class DataStore:
    def __init__(self, db_path: str, snapshot_root: str):
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.snapshot_root = Path(snapshot_root)

    # Write
    def save_incident(self, record: IncidentRecord) -> str: ...
    def save_near_miss(self, record: NearMissRecord) -> str: ...
    def save_alert(self, record: AlertRecord) -> str: ...

    # Read
    def get_incidents(self, limit: int = 50, offset: int = 0) -> list[IncidentRecord]: ...
    def get_near_misses(self, limit: int = 200) -> list[NearMissRecord]: ...
    def get_heatmap_data(self) -> list[tuple[float, float]]: ...
    def get_stats(self) -> dict: ...

    # Update
    def acknowledge_alert(self, alert_id: str): ...
    def mark_false_positive(self, alert_id: str): ...
```

### SnapshotStore
```python
class SnapshotStore:
    def __init__(self, root: Path):
        self.root = root

    def save(self, frame_id: str, frame: np.ndarray) -> str:
        date_dir = self.root / datetime.utcnow().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        path = date_dir / f"{frame_id}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return str(path.relative_to(self.root))
```

### RetentionManager
```python
class RetentionManager:
    def __init__(self, store: DataStore, max_frame_age_hours: int = 24):
        ...

    def run(self):
        # called once daily (threading.Timer or APScheduler)
        cutoff = datetime.utcnow() - timedelta(hours=self.max_frame_age_hours)
        # delete frames rows older than cutoff
        # do NOT delete incidents, near_misses, alerts
        # do NOT delete snapshot JPEGs referenced by incidents
```

## Config
```yaml
storage:
  db_path: data/safety.db
  snapshot_path: data/snapshots
  retention_hours: 24
```

## Scalability Hooks
- SQLite → PostgreSQL: change connection string only. All queries use SQLAlchemy ORM — zero SQL changes.
- `source_id` on every table: multi-camera queries are already filterable
- `get_heatmap_data()` returns `list[tuple[float, float]]` (normalized coords) — dashboard maps these to pixel space at render time, so resolution changes don't break historic data

## Constraints
- NO numpy arrays in the DB — snapshots are JPEGs on disk
- NO raw SQL strings anywhere in this module
- All writes inside `with Session() as s: s.commit()` — never leave sessions open
- Snapshot paths stored as relative strings — portable across machines

## Testing
- Use `db_path=":memory:"` for all unit tests
- Assert `get_incidents()` returns typed list, not raw rows
- Assert `save_incident()` returns the generated uuid
- Test `RetentionManager.run()` with seeded old rows — verify they're deleted and recent ones aren't