from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "fivsed_data.json"


_SECRET_HASH_KEYS = {
    "current_sha256", "reference_sha256", "firmware_hash", "sha256", "hash",
}


def _scrub_hash_fields(value):
    """Remove firmware/hash values from local audit storage recursively."""
    if isinstance(value, dict):
        return {k: _scrub_hash_fields(v) for k, v in value.items() if k not in _SECRET_HASH_KEYS}
    if isinstance(value, list):
        return [_scrub_hash_fields(v) for v in value]
    return value


class FIVSEDStorageManager:
    """Audit-only persistence.

    No trusted reference hashes or integrity decisions are stored here. The STM32
    owns both. This file contains only locally observed events and diagnostics.
    """

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file
        self._lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict:
        empty = {"targets": {}, "history": [], "logs": []}
        if not self.data_file.exists():
            self._save(empty)
            return empty
        try:
            raw = json.loads(self.data_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("storage root must be an object")
            cleaned = {
                "targets": raw.get("targets", {}) if isinstance(raw.get("targets", {}), dict) else {},
                "history": raw.get("history", []) if isinstance(raw.get("history", []), list) else [],
                "logs": raw.get("logs", []) if isinstance(raw.get("logs", []), list) else [],
            }
            cleaned = _scrub_hash_fields(cleaned)
            return cleaned
        except (OSError, ValueError, TypeError):
            self._save(empty)
            return empty

    def _save(self, data: dict | None = None) -> None:
        payload = data if data is not None else self.data
        tmp = self.data_file.with_suffix(self.data_file.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
            os.replace(tmp, self.data_file)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def record_target_observation(self, target: dict) -> None:
        # Target metadata is only observational; no reference hash is accepted.
        with self._lock:
            tid = str(target.get("id", ""))
            if not tid:
                return
            safe = {k: target.get(k) for k in (
                "id", "name", "manufacturer", "model", "type", "vid", "pid", "serial",
                "bus", "device_path", "interface", "status", "acquisition_method", "capability",
                "firmware_access", "jedec", "firmware_size", "slot", "stm32_slot", "stm32_target_id",
                "physical_uid", "logical_target_id", "reference_state", "metadata_valid",
                "bios_vendor", "bios_version", "bios_date", "uefi_version", "architecture",
                "cpu", "sku", "asset_tag", "uuid", "build_id",
            )}
            safe["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.data.setdefault("targets", {})[tid] = safe
            self._save()

    def get_target_observations(self) -> list[dict]:
        with self._lock:
            return list(self.data.get("targets", {}).values())

    def add_scan_record(self, record: dict) -> None:
        with self._lock:
            clean = _scrub_hash_fields(dict(record))
            self.data.setdefault("history", []).insert(0, clean)
            self.data["history"] = self.data["history"][:100]
            self._save()

    def get_history(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(100, int(limit)))
        with self._lock:
            return self.data.get("history", [])[:limit]

    def add_log(self, level: str, module: str, message: str) -> None:
        with self._lock:
            self.data.setdefault("logs", []).insert(
                0,
                {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": level,
                    "module": module,
                    "message": message,
                },
            )
            self.data["logs"] = self.data["logs"][:200]
            self._save()

    def get_logs(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(200, int(limit)))
        with self._lock:
            return self.data.get("logs", [])[:limit]


storage = FIVSEDStorageManager()
