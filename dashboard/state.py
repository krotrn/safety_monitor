"""Shared state between main.py and the dashboard.

main.py imports these containers and sets them before starting uvicorn.
The dashboard reads from them — never writes back into the core pipeline.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import numpy as np

# Latest annotated frame (set by main.py after drawing bounding boxes)
frame_store: Dict[str, Optional[np.ndarray]] = {"annotated": None}

# Async queue for live SeverityResult dicts pushed to WebSocket clients
event_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

# DataStore instance reference (set once by main.py at startup)
data_store_ref: Dict[str, Any] = {"store": None}
