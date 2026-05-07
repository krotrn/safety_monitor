from datetime import UTC, datetime
from pathlib import Path
import uuid

import pytest

from core.camera_manager import CameraManager, FileSource
from core.inference_engine import InferenceEngine
from core.models import DetectionResult, FrameMetadata

SAMPLE_PATH = "tests/sample.mp4"
MODEL_PATH = "models/yolov8n.onnx"


def test_file_source_reads_frames() -> None:
    source = FileSource(SAMPLE_PATH, target_fps=15, loop=False)
    try:
        frame = source.read()
        assert frame is not None
    finally:
        source.release()


def test_camera_manager_get_frame() -> None:
    source = FileSource(SAMPLE_PATH, target_fps=15, loop=True)
    manager = CameraManager(source, source_id="cam_test", buffer_size=2)
    manager.start()
    try:
        frame_meta = manager.get_frame(timeout=2.0)
        assert isinstance(frame_meta, FrameMetadata)
        assert frame_meta.frame_id
        assert frame_meta.timestamp
        assert frame_meta.source_id == "cam_test"
        assert frame_meta.raw_frame is not None
    finally:
        manager.stop()


def test_inference_engine_detects_when_model_present() -> None:
    if not Path(MODEL_PATH).exists():
        pytest.skip("model file not available")
    source = FileSource(SAMPLE_PATH, target_fps=15, loop=False)
    try:
        frame = source.read()
    finally:
        source.release()
    if frame is None:
        pytest.skip("sample video frame not available")
    frame_meta = FrameMetadata(
        frame_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        source_id="cam_01",
        raw_frame=frame,
    )
    engine = InferenceEngine(
        {
            "model_path": MODEL_PATH,
            "model_format": "onnx",
            "confidence_threshold": 0.5,
            "iou_threshold": 0.45,
            "target_size": [640, 640],
            "classes_of_interest": ["person", "car", "motorcycle", "truck", "bus"],
        }
    )
    result = engine.detect(frame_meta)
    assert isinstance(result, DetectionResult)
    assert result.frame_id == frame_meta.frame_id
    assert result.timestamp == frame_meta.timestamp
    assert result.source_id == frame_meta.source_id
    assert isinstance(result.detections, list)
    for det in result.detections:
        assert det.class_label
        assert 0.0 <= det.confidence <= 1.0
        for value in det.bbox_norm:
            assert 0.0 <= value <= 1.0
