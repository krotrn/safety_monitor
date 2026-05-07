from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from typing import Optional, Tuple

import cv2
import numpy as np

from core.models import FrameMetadata

logger = logging.getLogger(__name__)


class CameraSource(ABC):
    @abstractmethod
    def read(self) -> Optional[np.ndarray]:
        """Return a BGR frame or None on failure."""

    @abstractmethod
    def release(self) -> None:
        """Release hardware/file resources."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        ...


class USBCameraSource(CameraSource):
    def __init__(self, device_index: int = 0, resolution: Tuple[int, int] = (640, 480)) -> None:
        self._cap: Optional[cv2.VideoCapture] = None
        try:
            self._cap = cv2.VideoCapture(device_index)
            if not self._cap.isOpened():
                raise RuntimeError(f"USB camera not found at index {device_index}")
            width, height = resolution
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
        except Exception as exc:
            if self._cap is not None:
                self._cap.release()
            raise RuntimeError(f"Failed to open USB camera at index {device_index}: {exc}") from exc

    def read(self) -> Optional[np.ndarray]:
        try:
            if self._cap is None or not self._cap.isOpened():
                return None
            ok, frame = self._cap.read()
            return frame if ok else None
        except Exception as exc:
            logger.warning("USB camera read failed: %s", exc)
            return None

    def release(self) -> None:
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception as exc:
            logger.error("Failed to release USB camera: %s", exc)

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()


class IPCameraSource(CameraSource):
    def __init__(self, rtsp_url: str) -> None:
        self._rtsp_url = rtsp_url
        self._cap: Optional[cv2.VideoCapture] = None
        try:
            self._cap = cv2.VideoCapture(rtsp_url)
            if not self._cap.isOpened():
                raise RuntimeError("IP camera not reachable at startup")
        except Exception as exc:
            if self._cap is not None:
                self._cap.release()
            raise RuntimeError(f"Failed to open IP camera stream: {exc}") from exc

    def _reconnect(self) -> bool:
        for _ in range(3):
            try:
                if self._cap is not None:
                    self._cap.release()
                self._cap = cv2.VideoCapture(self._rtsp_url)
                if self._cap.isOpened():
                    return True
            except Exception as exc:
                logger.warning("IP camera reconnect failed: %s", exc)
            time.sleep(5)
        return False

    def read(self) -> Optional[np.ndarray]:
        try:
            if self._cap is None or not self._cap.isOpened():
                if not self._reconnect():
                    return None
            ok, frame = self._cap.read()
            if ok:
                return frame
            if self._reconnect():
                ok, frame = self._cap.read()
                return frame if ok else None
            return None
        except Exception as exc:
            logger.warning("IP camera read failed: %s", exc)
            return None

    def release(self) -> None:
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception as exc:
            logger.error("Failed to release IP camera: %s", exc)

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()


class FileSource(CameraSource):
    def __init__(
        self,
        path: str,
        target_fps: int = 15,
        loop: bool = True,
        resize_to: Optional[Tuple[int, int]] = None,
    ) -> None:
        if target_fps <= 0:
            raise ValueError("target_fps must be greater than 0")
        self._path = Path(path)
        self._target_fps = target_fps
        self._loop = loop
        self._resize_to = resize_to
        self._cap: Optional[cv2.VideoCapture] = None
        try:
            if not self._path.exists():
                raise RuntimeError(f"Video file not found: {path}")
            self._cap = cv2.VideoCapture(str(self._path))
            if not self._cap.isOpened():
                raise RuntimeError(f"Failed to open video file: {path}")
        except Exception as exc:
            if self._cap is not None:
                self._cap.release()
            raise RuntimeError(f"FileSource initialization failed: {exc}") from exc

    def read(self) -> Optional[np.ndarray]:
        try:
            if self._cap is None or not self._cap.isOpened():
                return None
            ok, frame = self._cap.read()
            if not ok:
                if self._loop:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = self._cap.read()
                if not ok:
                    self._cap.release()
                    return None
            if self._resize_to is not None:
                frame = cv2.resize(frame, self._resize_to)
            return frame
        except Exception as exc:
            logger.warning("FileSource read failed: %s", exc)
            return None

    def release(self) -> None:
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception as exc:
            logger.error("Failed to release FileSource: %s", exc)

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()


class CameraManager:
    def __init__(
        self,
        source: CameraSource,
        source_id: str = "cam_01",
        buffer_size: int = 30,
        frame_skip: int = 1,
        target_fps: int = 15,
    ) -> None:
        self._source = source
        self._source_id = source_id
        self._buffer = Queue(maxsize=buffer_size)
        self._frame_skip = max(1, frame_skip)
        self._target_fps = target_fps
        self._frame_interval = 1.0 / max(1, target_fps)
        self._dropped_frames = 0
        self._stop_event = Event()
        self._thread: Optional[Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            self._source.release()
        except Exception as exc:
            logger.error("Failed to release camera source: %s", exc)

    def get_frame(self, timeout: float = 1.0) -> FrameMetadata:
        return self._buffer.get(timeout=timeout)

    @property
    def buffer_size(self) -> int:
        return self._buffer.maxsize

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    def _capture_loop(self) -> None:
        retry_count = 0
        read_count = 0
        last_drop_log_time = 0.0
        next_frame_time = time.monotonic()
        while not self._stop_event.is_set():
            # ── Wall-clock throttle to maintain real-time playback ──
            now = time.monotonic()
            sleep_dur = next_frame_time - now
            if sleep_dur > 0:
                time.sleep(sleep_dur)
            next_frame_time = time.monotonic() + self._frame_interval

            frame = self._source.read()
            if frame is None:
                if not self._source.is_open:
                    logger.info("Source exhausted — stopping capture.")
                    break
                retry_count += 1
                if retry_count >= 3:
                    logger.error("Camera read failed 3 times, sleeping 2s")
                    time.sleep(2)
                    retry_count = 0
                continue
            retry_count = 0
            read_count += 1
            if read_count % self._frame_skip != 0:
                continue
            meta = FrameMetadata(
                frame_id=str(uuid.uuid4()),
                timestamp=datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat(),
                source_id=self._source_id,
                raw_frame=frame,
            )
            if self._buffer.full():
                try:
                    self._buffer.get_nowait()
                except Exception:
                    pass
                self._dropped_frames += 1
                now = time.monotonic()
                if now - last_drop_log_time > 5.0:
                    logger.warning(
                        "FrameBuffer full — dropped %d frame(s) so far",
                        self._dropped_frames,
                    )
                    last_drop_log_time = now
            self._buffer.put(meta)
