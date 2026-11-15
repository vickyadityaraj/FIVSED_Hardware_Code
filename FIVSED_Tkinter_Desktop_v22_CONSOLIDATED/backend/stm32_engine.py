from __future__ import annotations

import threading
import time
import uuid
from typing import Optional

from .acquisition import (
    ESP32FlashProvider,
    SPIFlashProvider,
    RPiW25Q64Provider,
    AuthorizedSerialProvider,
    USBStorageProvider,
    UnsupportedProvider,
)
from .hardware_reader import hardware_reader
from .storage import storage
from .stm32_link import STM32ProtocolError, stm32_link


class ScanManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._scans: dict[str, dict] = {}
        self._providers = {
            SPIFlashProvider.name: SPIFlashProvider(),
            RPiW25Q64Provider.name: RPiW25Q64Provider(),
            AuthorizedSerialProvider.name: AuthorizedSerialProvider(),
            USBStorageProvider.name: USBStorageProvider(),
            ESP32FlashProvider.name: ESP32FlashProvider(),
            UnsupportedProvider.name: UnsupportedProvider(),
        }

    def _new_scan(self, target: dict) -> dict:
        scan_id = str(uuid.uuid4())
        record = {
            "scan_id": scan_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_id": target.get("id"),
            "target_name": target.get("name", "N/A"),
            "interface": target.get("interface", "N/A"),
            "status": "SCANNING",
            "stage": "TARGET_SELECTED",
            "bytes_processed": 0,
            "total_bytes": target.get("firmware_size") or 0,
            "result": None,
            "reason": "",
            "stm32_authoritative": True,
            "stm32_status": "CONNECTED",
            "firmware_size": target.get("firmware_size"),
            "duration_ms": None,
        }
        with self._lock:
            self._scans[scan_id] = record
            if len(self._scans) > 200:
                finished = [sid for sid, item in self._scans.items() if item.get("status") == "COMPLETE"]
                for sid in finished[: max(0, len(self._scans) - 200)]:
                    self._scans.pop(sid, None)
        return dict(record)

    def get(self, scan_id: str) -> Optional[dict]:
        with self._lock:
            item = self._scans.get(scan_id)
            return dict(item) if item else None

    def _update(self, scan_id: str, **fields) -> None:
        with self._lock:
            if scan_id in self._scans:
                self._scans[scan_id].update(fields)

    @staticmethod
    def _audit_level(result: str) -> str:
        if result == "HASH_MISMATCH":
            return "SECURITY"
        if result in ("READ_ERROR", "FIRMWARE_ACCESS_PROTECTED"):
            return "WARNING"
        return "INFO"

    def _run(self, scan_id: str, target: dict) -> None:
        started = time.monotonic()
        try:
            if not stm32_link.ensure_connected():
                raise STM32ProtocolError(stm32_link.last_error or "STM32 not connected")

            provider_name = target.get("acquisition_method") or "UNSUPPORTED"
            provider = self._providers.get(provider_name, self._providers[UnsupportedProvider.name])
            probe = provider.probe(target)
            if not probe.supported:
                self._update(
                    scan_id,
                    status="COMPLETE",
                    stage="FIRMWARE_ACQUISITION_UNSUPPORTED",
                    result=probe.status,
                    reason=probe.reason,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    stm32_status="CONNECTED",
                )
                storage.add_scan_record(self.get(scan_id) or {})
                storage.add_log("WARNING", "ACQUISITION", f"{target.get('name', target.get('id'))}: {probe.status} - {probe.reason}")
                return

            self._update(scan_id, stage="ACQUIRING_FIRMWARE")

            def progress(done: int, total: int, stage: str) -> None:
                self._update(
                    scan_id,
                    stage=stage or "STREAMING_TO_STM32",
                    bytes_processed=max(0, done),
                    total_bytes=max(0, total),
                )

            result = provider.acquire(target, progress=progress)
            meta = result.metadata or {}
            authoritative_result = str(meta.get("result", result.status))
            self._update(
                scan_id,
                status="COMPLETE",
                stage="RESULT_RECEIVED",
                result=authoritative_result,
                reason=result.reason or str(meta.get("reason", "")),
                firmware_size=meta.get("firmware_size") or target.get("firmware_size"),
                bytes_processed=meta.get("firmware_size") or target.get("firmware_size") or 0,
                total_bytes=meta.get("firmware_size") or target.get("firmware_size") or 0,
                duration_ms=meta.get("duration_ms") or int((time.monotonic() - started) * 1000),
                stm32_status="CONNECTED",
            )
            record = self.get(scan_id) or {}
            storage.add_scan_record(record)
            storage.record_target_observation(target)
            storage.add_log(self._audit_level(authoritative_result), "STM32_CORE", f"{target.get('name', target.get('id'))}: {authoritative_result}")
        except STM32ProtocolError as exc:
            reason = str(exc) or "STM32 communication error"
            self._update(
                scan_id,
                status="COMPLETE",
                stage="COMMUNICATION_ERROR",
                result="READ_ERROR",
                reason=reason,
                duration_ms=int((time.monotonic() - started) * 1000),
                stm32_status="DISCONNECTED" if not stm32_link.connected else "ERROR",
            )
            record = self.get(scan_id) or {}
            storage.add_scan_record(record)
            storage.add_log("ERROR", "STM32_LINK", f"Scan {scan_id}: {reason}")
        except Exception as exc:
            reason = f"Unexpected acquisition error: {exc}"
            self._update(
                scan_id,
                status="COMPLETE",
                stage="ERROR",
                result="READ_ERROR",
                reason=reason,
                duration_ms=int((time.monotonic() - started) * 1000),
                stm32_status="ERROR",
            )
            record = self.get(scan_id) or {}
            storage.add_scan_record(record)
            storage.add_log("ERROR", "SCAN_ENGINE", reason)

    def start(self, target: dict) -> dict:
        with self._lock:
            existing = next((item for item in self._scans.values()
                             if item.get("target_id") == target.get("id") and item.get("status") == "SCANNING"), None)
            if existing:
                raise RuntimeError("A scan is already running for this target.")
        record = self._new_scan(target)
        thread = threading.Thread(target=self._run, args=(record["scan_id"], target), daemon=True, name=f"fivsed-scan-{record['scan_id'][:8]}")
        thread.start()
        return record

    def targets(self) -> list[dict]:
        return hardware_reader.detect_connected_targets()


stm32_engine = ScanManager()
