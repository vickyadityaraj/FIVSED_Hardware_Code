from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from .base import AcquisitionResult, FirmwareAcquisitionProvider
from ..config import config
from ..stm32_link import STM32ProtocolError, stm32_link


class ESP32FlashProvider(FirmwareAcquisitionProvider):
    """Authorized Espressif flash acquisition through the ROM bootloader.

    This provider only uses read-only esptool operations (flash-id/read-flash). It does not
    erase, write, bypass protection, or ask the target to calculate a hash. The acquired image
    is streamed into STM32, which owns the integrity decision.
    """

    name = "ESP32_FLASH_AUTHORIZED"
    _PROTECTED_PATTERNS = (
        "flash encryption is enabled",
        "flash encryption",
        "secure boot",
        "read protected",
        "access denied",
        "permission denied",
        "failed to read",
    )

    def _port(self, target: dict) -> str:
        return str(target.get("interface") or "").strip()

    def _command_prefix(self) -> list[str]:
        configured = config.acquisition.esptool_command.strip()
        if configured:
            return shlex.split(configured)
        return [sys.executable, "-m", "esptool"]

    def _run(self, port: str, args: list[str], timeout: int) -> tuple[int, str]:
        command = self._command_prefix() + ["--port", port, "--baud", str(config.acquisition.esptool_baud)] + args
        try:
            proc = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            return proc.returncode, proc.stdout or ""
        except FileNotFoundError as exc:
            return 127, str(exc)
        except subprocess.TimeoutExpired as exc:
            return 124, (exc.stdout or "" if isinstance(exc.stdout, str) else "") + "\nTimed out"
        except OSError as exc:
            return 126, str(exc)

    @staticmethod
    def _parse_flash_size(output: str) -> int | None:
        match = re.search(r"Detected flash size:\s*([0-9]+(?:\.[0-9]+)?)\s*([KMG]?B)", output, re.I)
        if not match:
            return None
        value = float(match.group(1))
        unit = match.group(2).upper()
        multiplier = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}.get(unit)
        if multiplier is None:
            return None
        return int(value * multiplier)

    @classmethod
    def _protected(cls, output: str) -> bool:
        text = output.lower()
        return any(pattern in text for pattern in cls._PROTECTED_PATTERNS)

    def probe(self, target: dict) -> AcquisitionResult:
        port = self._port(target)
        if not port:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "No serial interface is associated with this target.")
        likely = str(target.get("acquisition_method") or "") == self.name or str(target.get("manufacturer") or "").lower().find("espressif") >= 0
        vid = str(target.get("vid") or "").upper()
        if not likely and vid not in {"303A"}:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "The device is not identified as an Espressif target.")

        code, output = self._run(port, ["flash-id"], timeout=15)
        if code != 0:
            if self._protected(output):
                return AcquisitionResult(False, self.name, "FIRMWARE_ACCESS_PROTECTED", "Espressif bootloader reported protected flash access; no bypass was attempted.", {"tool_output": output[-1200:]})
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", output.strip()[-1200:] or f"esptool exited with code {code}")
        size = self._parse_flash_size(output)
        if size is None:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", "esptool identified the device but did not report a usable flash size.", {"tool_output": output[-1200:]})
        if size <= 0 or size > config.acquisition.max_firmware_bytes:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", f"Detected flash size {size} bytes exceeds the configured acquisition limit.", {"flash_size": size})
        return AcquisitionResult(True, self.name, "SUPPORTED", "Espressif flash is readable through the authorized bootloader.", {"flash_size": size, "tool_output": output[-1200:]})

    def acquire(self, target: dict, progress: Optional[Callable[[int, int, str], None]] = None) -> AcquisitionResult:
        probe = self.probe(target)
        if not probe.supported:
            return probe

        port = self._port(target)
        size = int(probe.metadata.get("flash_size", 0))
        slot = int(target.get("slot", config.acquisition.esp32_stm32_slot))
        stm_target_id = str(target.get("stm32_target_id") or "")
        if not stm_target_id:
            stm_target_id = f"esp32:{target.get('id', port)}"
        if len(stm_target_id) > 31:
            # Stable IDs from discovery are deterministic. Truncate only at the STM32 protocol boundary.
            stm_target_id = stm_target_id[-31:]

        if progress:
            progress(0, size, "ACQUIRING_FIRMWARE")

        try:
            with tempfile.TemporaryDirectory(prefix="fivsed-esp32-") as temp_dir:
                image_path = Path(temp_dir) / "firmware.bin"
                code, output = self._run(
                    port,
                    ["read-flash", "0", str(size), str(image_path)],
                    timeout=max(config.acquisition.esptool_timeout_seconds, int(size / 8192) + 60),
                )
                if code != 0:
                    if self._protected(output):
                        return AcquisitionResult(False, self.name, "FIRMWARE_ACCESS_PROTECTED", "Espressif flash access is protected; FIVSED did not attempt to bypass it.", {"tool_output": output[-1600:]})
                    return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", output.strip()[-1600:] or f"esptool read-flash exited with code {code}")
                actual = image_path.stat().st_size if image_path.exists() else 0
                if actual != size:
                    return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", f"Firmware acquisition produced {actual} bytes; expected {size} bytes.", {"tool_output": output[-1200:]})
                if progress:
                    progress(0, size, "STREAMING_TO_STM32")
                result = stm32_link.stream_file(image_path, slot, stm_target_id, progress=progress)
                result["acquisition_method"] = self.name
                result["source_device_id"] = target.get("id")
                return AcquisitionResult(True, self.name, str(result.get("result", "READ_ERROR")), str(result.get("reason", "")), metadata=result)
        except (OSError, STM32ProtocolError) as exc:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", str(exc) or "Firmware acquisition failed")
