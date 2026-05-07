# Module Spec: alert_manager

## Purpose
Receive SeverityResult, deduplicate alerts, and fan-out to all active response channels (Telegram, SMS, GPIO). Never alert twice for the same ongoing incident.

## Location
`core/alert_manager.py`

## Responsibilities
- Consume SeverityResult from severity_engine
- Apply cooldown deduplication per event_type + source_id
- Fan-out to configured channels based on action_tier
- Write AlertRecord to data_store
- Expose acknowledge and false-positive endpoints (called by dashboard)

## Internal Components

### AlertDeduplicator
```python
class AlertDeduplicator:
    def __init__(self, cooldown_seconds: int = 30):
        self._last_alert: dict[str, float] = {}  # key: f"{source_id}:{event_type}"

    def should_alert(self, source_id: str, event_type: str) -> bool:
        key = f"{source_id}:{event_type}"
        return time.time() - self._last_alert.get(key, 0) > self.cooldown_seconds

    def record(self, source_id: str, event_type: str):
        self._last_alert[f"{source_id}:{event_type}"] = time.time()
```

### AlertDispatcher
```python
class AlertDispatcher:
    def __init__(self, channels: list[AlertChannel]):
        self.channels = channels

    async def dispatch(self, severity_result: SeverityResult, snapshot: np.ndarray):
        for ch in self.channels:
            await ch.send(severity_result, snapshot)
```

### Channel Interface
```python
class AlertChannel(ABC):
    @abstractmethod
    async def send(self, result: SeverityResult, snapshot: np.ndarray): ...
```

### TelegramAlertChannel
- Uses `python-telegram-bot` async API
- Sends JPEG snapshot + caption with severity score, event type, timestamp, camera ID
- Caption format: `🚨 PersonOnGround | Score: 82/100 | cam_01 | 2024-01-15T10:32:01`
- Attach frame via `bot.send_photo(photo=jpeg_bytes, caption=...)`

### PhysicalTriggerChannel
- GPIO pin HIGH for configured duration
- `flag` tier: 1 short pulse (500ms)
- `alert` tier: continuous HIGH until acknowledged
- Abstract behind `PhysicalOutput` interface — stub for non-Pi environments:
  ```python
  class GPIOOutput(PhysicalOutput):
      def trigger(self, duration_ms: int): ...
  class StubOutput(PhysicalOutput):  # for dev/testing
      def trigger(self, duration_ms: int): print(f"[GPIO stub] {duration_ms}ms")
  ```

### SMSAlertChannel (optional)
- Twilio REST API
- Text-only fallback — omit for minor project demo

## Output: AlertRecord
```python
@dataclass
class AlertRecord:
    alert_id: str          # uuid4
    severity_result_id: str
    timestamp: str         # ISO8601
    source_id: str
    channels_triggered: list[str]   # ["telegram", "gpio"]
    acknowledged: bool = False
    false_positive: bool = False
    acknowledged_at: str | None = None
```

## Action Tier → Channel Mapping
| Tier    | Telegram | GPIO   | DB log |
|---------|----------|--------|--------|
| silent  | ✗        | ✗      | ✓      |
| flag    | ✗        | pulse  | ✓      |
| alert   | ✓ photo  | continuous | ✓  |

## Config
```yaml
alerts:
  telegram_token: ""
  telegram_chat_id: ""
  cooldown_seconds: 30
  gpio_pin: 17
  gpio_flag_duration_ms: 500
  channels:
    - telegram
    - gpio
```

## Scalability Hooks
- `channels` list in config — add new channels without touching AlertManager logic
- Cooldown keyed on `source_id:event_type` — multi-camera safe
- `AlertRecord.acknowledged` drives dashboard UI and potential auto-escalation in major project

## Constraints
- NEVER call Telegram API synchronously in the frame loop — always `asyncio.create_task()`
- Telegram token must come from config/env, never hardcoded
- GPIO calls must be wrapped in try/except — hardware may not be present

## Testing
- Mock `bot.send_photo` — assert it's called with correct caption fields
- Mock `GPIOOutput.trigger` — assert duration matches tier
- Assert `should_alert()` returns False within cooldown window
- Use `StubOutput` for all non-hardware tests