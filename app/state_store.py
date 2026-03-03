from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class StateStore:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._lock = Lock()
        self._state: dict[str, Any] = {"users": {}}
        self._load()

    def _ensure_dir(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _persist(self) -> None:
        try:
            self._ensure_dir()
            self.file_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            # In serverless/read-only environments keep in-memory state only.
            pass

    def _load(self) -> None:
        with self._lock:
            try:
                if not self.file_path.exists():
                    self._persist()
                    return

                raw = self.file_path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and isinstance(parsed.get("users"), dict):
                    self._state = parsed
            except Exception:
                self._state = {"users": {}}
                self._persist()

    def get_user(self, phone: str) -> dict[str, Any] | None:
        return self._state["users"].get(phone)

    def set_user(self, phone: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.get_user(phone) or {}
            current.update(patch)
            current["updatedAt"] = datetime.now(timezone.utc).isoformat()
            self._state["users"][phone] = current
            self._persist()
            return current
