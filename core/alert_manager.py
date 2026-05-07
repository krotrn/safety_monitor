from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future
from threading import Thread
from typing import List, Optional

import cv2
import numpy as np
from telegram import Bot
from telegram.request import HTTPXRequest

from core.data_store import AlertRecord, DataStore
from core.models import SeverityResult

logger = logging.getLogger(__name__)

_DISPATCH_FILTER_ADDED = False


class _DispatchLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.name == "__main__" and message.startswith("dispatch alert |"):
            return False
        return True


class AlertDeduplicator:
    def __init__(self, cooldown_seconds: int = 30) -> None:
        self.cooldown_seconds = int(cooldown_seconds)
        self._last_alert: dict[str, float] = {}

    def check_and_record(self, source_id: str, event_type: str) -> bool:
        key = f"{source_id}:{event_type}"
        now = time.time()
        if now - self._last_alert.get(key, 0.0) < self.cooldown_seconds:
            return False
        self._last_alert[key] = now
        return True


class AlertChannel(ABC):
    name: str

    @abstractmethod
    async def send(self, result: SeverityResult, snapshot: np.ndarray) -> None:
        ...


class TelegramAlertChannel(AlertChannel):
    name = "telegram"

    def __init__(self, token: str, chat_id: str, bot: Optional[Bot] = None) -> None:
        self._token = token
        self._chat_id = chat_id
        self._injected_bot = bot  # only used in tests

    async def send(self, result: SeverityResult, snapshot: np.ndarray) -> None:
        try:
            ok, buffer = cv2.imencode(".jpg", snapshot, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if not ok:
                raise RuntimeError("cv2.imencode returned False")
            caption = (
                f"🚨 {result.event_type} | Score: {int(round(result.severity_score))}/100 | "
                f"{result.source_id} | {result.timestamp}"
            )
            photo_stream = io.BytesIO(buffer.tobytes())
            if self._injected_bot is not None:
                bot = self._injected_bot
            else:
                request = HTTPXRequest(connect_timeout=10.0, read_timeout=30.0)
                bot = Bot(token=self._token, request=request)
            await bot.send_photo(chat_id=self._chat_id, photo=photo_stream, caption=caption)
        except Exception as exc:
            raise RuntimeError(f"Failed to send Telegram alert: {exc}") from exc


class StubAlertChannel(AlertChannel):
    name = "stub"

    async def send(self, result: SeverityResult, snapshot: np.ndarray) -> None:
        logger.info(
            "[StubAlert] %s score=%.1f tier=%s",
            result.event_type,
            result.severity_score,
            result.action_tier,
        )


class StubGPIOOutput(AlertChannel):
    name = "gpio"

    async def send(self, result: SeverityResult, snapshot: np.ndarray) -> None:
        if result.action_tier == "alert":
            logger.info("[StubGPIOOutput] Triggering BUZZER and LED for 2 seconds")
        else:
            logger.info("[StubGPIOOutput] Tier is %s, no GPIO action needed", result.action_tier)


class AlertManager:
    def __init__(self, store: DataStore, channels: List[AlertChannel], cooldown_seconds: int = 30):
        global _DISPATCH_FILTER_ADDED
        if not _DISPATCH_FILTER_ADDED:
            logging.getLogger().addFilter(_DispatchLogFilter())
            _DISPATCH_FILTER_ADDED = True
        self._store = store
        self._channels = channels
        self._deduplicator = AlertDeduplicator(cooldown_seconds=cooldown_seconds)

    def dispatch(self, severity_result: SeverityResult, incident_id: str):
        if not self._deduplicator.check_and_record(
            severity_result.source_id,
            severity_result.event_type,
        ):
            logger.info(
                "suppressed by cooldown | %s %s",
                severity_result.source_id,
                severity_result.event_type,
            )
            return None
        logger.info(
            "dispatch alert | %s score=%.1f",
            severity_result.event_type,
            severity_result.severity_score,
        )
        try:
            channels_triggered = [channel.name for channel in self._channels]
            record = AlertRecord(
                severity_result_id=incident_id,
                source_id=severity_result.source_id,
                channels_triggered=json.dumps(channels_triggered),
            )
            self._store.save_alert(record)
        except Exception as exc:
            logger.error("Failed to save alert record: %s", exc)
        future: Future = Future()
        thread = Thread(
            target=self._dispatch_sync,
            args=(severity_result, future),
            daemon=True,
        )
        thread.start()
        return future

    def acknowledge_alert(self, alert_id: str) -> None:
        try:
            self._store.acknowledge_alert(alert_id)
        except Exception as exc:
            raise RuntimeError(f"Failed to acknowledge alert {alert_id}: {exc}") from exc

    def mark_false_positive(self, alert_id: str) -> None:
        try:
            self._store.mark_false_positive(alert_id)
        except Exception as exc:
            raise RuntimeError(f"Failed to mark false positive {alert_id}: {exc}") from exc

    async def _dispatch_async(self, severity_result: SeverityResult) -> None:
        for channel in self._channels:
            try:
                await channel.send(severity_result, severity_result.snapshot)
            except Exception as exc:
                logger.error("Alert channel %s failed: %s", channel.name, exc)

    def _dispatch_sync(self, severity_result: SeverityResult, future: Future) -> None:
        try:
            asyncio.run(self._dispatch_async(severity_result))
            if not future.done():
                future.set_result(True)
        except Exception as exc:
            logger.error("Alert dispatch failed: %s", exc)
            if not future.done():
                future.set_exception(exc)
