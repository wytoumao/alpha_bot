from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

import structlog


class StateStore:
    def __init__(self, path: Path, ttl: timedelta):
        self.path = path
        self.ttl = ttl
        self.logger = structlog.get_logger(__name__)
        self._state: Dict[str, str] = {}
        self._load()

    def was_notified(self, key: str) -> bool:
        return key in self._state

    def mark_notified(self, key: str, now: datetime) -> None:
        self._state[key] = now.isoformat()
        self._persist()

    def prune(self, now: datetime) -> None:
        expiry_threshold = now - self.ttl
        original_size = len(self._state)
        self._state = {
            key: value
            for key, value in self._state.items()
            if datetime.fromisoformat(value) >= expiry_threshold
        }
        if len(self._state) != original_size:
            self._persist()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._state = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            self.logger.warning("state.load_failed", path=str(self.path), error=str(exc))
            self._state = {}

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._state, handle)
