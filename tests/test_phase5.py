import uuid
from datetime import UTC, datetime

import numpy as np

from core.alert_manager import AlertManager, TelegramAlertChannel
from core.data_store import DataStore, IncidentRecord
from core.models import SeverityResult


class DummyBot:
    def __init__(self) -> None:
        self.calls = []

    async def send_photo(self, chat_id, photo, caption):
        self.calls.append({"chat_id": chat_id, "caption": caption})


def make_severity_result(score: float, tier: str, event_type: str) -> SeverityResult:
    return SeverityResult(
        frame_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC).replace(microsecond=0).isoformat(),
        source_id="cam_01",
        severity_score=score,
        event_type=event_type,
        triggered_rules=[event_type],
        action_tier=tier,
        snapshot=np.zeros((10, 10, 3), dtype=np.uint8),
        involved_track_ids=[],
    )


def test_telegram_alert_fires_on_alert_tier(tmp_path) -> None:
    store = DataStore(":memory:", str(tmp_path))
    incident = IncidentRecord(
        source_id="cam_01",
        severity_score=75.0,
        event_type="PersonOnGround",
        triggered_rules="[]",
        snapshot_path=None,
    )
    incident_id = store.save_incident(incident)

    bot = DummyBot()
    channel = TelegramAlertChannel("token", "chat", bot=bot)
    manager = AlertManager(store, [channel], cooldown_seconds=0)

    severity = make_severity_result(75.0, "alert", "PersonOnGround")
    future = manager.dispatch(severity, incident_id)
    assert future is not None
    future.result(timeout=2)

    assert len(bot.calls) == 1
    caption = bot.calls[0]["caption"]
    assert "PersonOnGround" in caption
    assert "Score:" in caption
    assert "cam_01" in caption


def test_cooldown_suppresses_duplicate_alerts(tmp_path) -> None:
    store = DataStore(":memory:", str(tmp_path))
    incident = IncidentRecord(
        source_id="cam_01",
        severity_score=90.0,
        event_type="PersonOnGround",
        triggered_rules="[]",
        snapshot_path=None,
    )
    incident_id = store.save_incident(incident)

    bot = DummyBot()
    channel = TelegramAlertChannel("token", "chat", bot=bot)
    manager = AlertManager(store, [channel], cooldown_seconds=60)

    severity = make_severity_result(90.0, "alert", "PersonOnGround")
    future = manager.dispatch(severity, incident_id)
    assert future is not None
    future.result(timeout=2)

    suppressed = manager.dispatch(severity, incident_id)
    assert suppressed is None
    assert len(bot.calls) == 1
