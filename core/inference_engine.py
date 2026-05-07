from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np


os.environ.setdefault("ORT_EXECUTION_PROVIDER", "CPUExecutionProvider")

from ultralytics import YOLO

from core.models import Detection, DetectionResult, FrameMetadata

logger = logging.getLogger(__name__)


class FramePreprocessor:
    def __init__(self, target_size: Tuple[int, int] = (640, 640)) -> None:
        self._target_size = (int(target_size[0]), int(target_size[1]))

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        return cv2.resize(frame, self._target_size)


class ModelLoader:
    def __init__(self, model_path: str, model_format: str = "onnx") -> None:
        self._model_path = model_path
        self._model_format = model_format

    def load(self) -> YOLO:
        try:
            path = Path(self._model_path)
            if not path.exists():
                raise RuntimeError(f"Model file not found: {self._model_path}")
            return YOLO(str(path), task="detect")
        except Exception as exc:
            raise RuntimeError(f"Failed to load model ({self._model_format}): {exc}") from exc


class InferenceEngine:
    def __init__(self, config: dict) -> None:
        self._confidence_threshold = float(config["confidence_threshold"])
        self._classes_of_interest = list(config.get("classes_of_interest", []))
        target_size = tuple(config.get("target_size", (640, 640)))
        self._preprocessor = FramePreprocessor(target_size=target_size)
        self._iou_threshold = config.get("iou_threshold")
        loader = ModelLoader(
            model_path=config["model_path"],
            model_format=config.get("model_format", "onnx"),
        )
        self._model = loader.load()

    def detect(self, frame_meta: FrameMetadata) -> DetectionResult:
        empty_result = DetectionResult(
            frame_id=frame_meta.frame_id,
            timestamp=frame_meta.timestamp,
            source_id=frame_meta.source_id,
            detections=[],
        )
        try:
            processed = self._preprocessor.preprocess(frame_meta.raw_frame)
            track_kwargs = {
                "persist": True,
                "conf": self._confidence_threshold,
                "verbose": False,
                "device": "cpu",
            }
            if self._iou_threshold is not None:
                track_kwargs["iou"] = float(self._iou_threshold)
            results = self._model.track(processed, **track_kwargs)
            detections: List[Detection] = []
            if results and len(results) > 0 and results[0].boxes is not None:
                h, w = frame_meta.raw_frame.shape[:2]
                ph, pw = processed.shape[:2]
                scale_x = w / pw if pw else 1.0
                scale_y = h / ph if ph else 1.0
                for box in results[0].boxes:
                    label = self._model.names[int(box.cls)]
                    if self._classes_of_interest and label not in self._classes_of_interest:
                        continue
                    confidence = float(box.conf)
                    if confidence < self._confidence_threshold:
                        continue
                    track_id = int(box.id.item()) if box.id is not None else -1
                    x1f, y1f, x2f, y2f = box.xyxy[0].tolist()
                    x1 = int(x1f * scale_x)
                    y1 = int(y1f * scale_y)
                    x2 = int(x2f * scale_x)
                    y2 = int(y2f * scale_y)
                    x1 = max(0, min(x1, w))
                    x2 = max(0, min(x2, w))
                    y1 = max(0, min(y1, h))
                    y2 = max(0, min(y2, h))
                    detections.append(
                        Detection(
                            object_id=str(uuid.uuid4()),
                            class_label=label,
                            confidence=confidence,
                            bbox=[x1, y1, x2, y2],
                            bbox_norm=[x1 / w, y1 / h, x2 / w, y2 / h],
                            track_id=track_id,
                        )
                    )
            return DetectionResult(
                frame_id=frame_meta.frame_id,
                timestamp=frame_meta.timestamp,
                source_id=frame_meta.source_id,
                detections=detections,
            )
        except Exception as exc:
            logger.warning("Inference failed on frame %s: %s", frame_meta.frame_id, exc)
            return empty_result
