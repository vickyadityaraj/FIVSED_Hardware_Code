from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Optional

from .base import AcquisitionResult, FirmwareAcquisitionProvider
from ..config import config
from ..stm32_link import STM32ProtocolError, stm32_link

try:
    import spidev  # type: ignore
except Exception:  # pragma: no cover - runtime capability check
    spidev = None


CMD_JEDEC_ID = 0x9F
CMD_READ_UNIQUE_ID = 0x4B
CMD_READ_DATA = 0x03
W25Q64_JEDEC = bytes((0xEF, 0x40, 0x17))
READ_CHUNK = 4096
META_OFFSET = 0x1000
META_HEADER = b"FIVSED-META\x00"
META_READ_SIZE = 512


def _sanitize_logical_id(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._:-]", "-", value.strip())
    if value:
        return value[:31]
    return fallback[:31]


class RPiW25Q64Provider(FirmwareAcquisitionProvider):
    """Read a real W25Q64 attached to Raspberry Pi SPI1.

    Raspberry Pi performs acquisition only. It may parse the target's embedded
    display metadata, but that metadata is untrusted presentation data. The
    physical W25Q64 factory unique ID remains separate from the operator-facing
    logical identity. The complete raw image is forwarded to STM32, which owns
    SHA-256, trusted-reference storage, and the integrity decision.
    """

    name = "RPI_W25Q64_SPI"

    def _open(self):
        if spidev is None:
            raise RuntimeError("Python spidev module is not installed")
        spi = spidev.SpiDev()
        spi.open(config.acquisition.rpi_spi_bus, config.acquisition.rpi_spi_device)
        spi.max_speed_hz = config.acquisition.rpi_spi_speed_hz
        spi.mode = 0
        spi.bits_per_word = 8
        spi.lsbfirst = False
        spi.cshigh = False
        return spi

    def _read_jedec(self, spi) -> bytes:
        data = bytes(spi.xfer2([CMD_JEDEC_ID, 0x00, 0x00, 0x00]))
        if len(data) != 4:
            raise IOError("W25Q64 JEDEC read returned an unexpected length")
        return data[1:4]

    def _read_unique_id(self, spi) -> bytes:
        # 0x4B + four dummy bytes + 8-byte factory unique ID.
        data = bytes(spi.xfer2([CMD_READ_UNIQUE_ID] + [0x00] * 12))
        if len(data) != 13:
            raise IOError("W25Q64 unique-ID read returned an unexpected length")
        return data[5:13]

    @staticmethod
    def _target_id(unique_id: bytes) -> str:
        return "rpi-w25q64-" + unique_id.hex()

    @staticmethod
    def _logical_id(metadata: dict[str, str], unique_id: bytes) -> str:
        # The embedded SERIAL is used only as a stable logical/operator identity.
        # It never replaces the physical factory UID used for hardware evidence.
        serial = metadata.get("SERIAL", "").strip()
        if serial:
            return _sanitize_logical_id(serial, "rpi-w25q64-" + unique_id.hex())
        uuid_value = metadata.get("UUID", "").strip()
        if uuid_value:
            return _sanitize_logical_id(uuid_value, "rpi-w25q64-" + unique_id.hex())
        return "rpi-w25q64-" + unique_id.hex()

    @staticmethod
    def _parse_metadata(raw: bytes) -> dict[str, str]:
        if len(raw) < len(META_HEADER) + 4 or not raw.startswith(META_HEADER):
            return {}
        length = int.from_bytes(raw[len(META_HEADER):len(META_HEADER) + 4], "little")
        start = len(META_HEADER) + 4
        if length <= 0 or length > len(raw) - start or length > 2048:
            return {}
        body = raw[start:start + length]
        try:
            text = body.decode("ascii")
        except UnicodeDecodeError:
            return {}
        result: dict[str, str] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().upper()
            value = value.strip()
            if not key or not value or len(key) > 48 or len(value) > 160:
                continue
            result[key] = value
        return result

    def _read_metadata(self, spi) -> dict[str, str]:
        request = [
            CMD_READ_DATA,
            (META_OFFSET >> 16) & 0xFF,
            (META_OFFSET >> 8) & 0xFF,
            META_OFFSET & 0xFF,
        ] + [0x00] * META_READ_SIZE
        reply = bytes(spi.xfer2(request))
        if len(reply) != META_READ_SIZE + 4:
            raise IOError("W25Q64 metadata read returned an unexpected length")
        return self._parse_metadata(reply[4:])

    def probe(self, target: dict) -> AcquisitionResult:
        if target.get("acquisition_method") != self.name:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "Target is not the Raspberry Pi W25Q64 SPI target.")
        if spidev is None:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "Python spidev module is not installed.")

        spi = None
        started = time.monotonic()
        try:
            spi = self._open()
            jedec = self._read_jedec(spi)
            if jedec != W25Q64_JEDEC:
                return AcquisitionResult(
                    False,
                    self.name,
                    "FIRMWARE_READ_UNSUPPORTED",
                    f"Detected SPI NOR JEDEC {jedec.hex().upper()}, expected W25Q64JV EF4017.",
                    {"jedec": jedec.hex()},
                )
            unique_id = self._read_unique_id(spi)
            if len(unique_id) != 8 or unique_id == b"\x00" * 8 or unique_id == b"\xFF" * 8:
                return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", "W25Q64 returned an invalid factory unique ID.")
            metadata = self._read_metadata(spi)
            logical_id = self._logical_id(metadata, unique_id)
            return AcquisitionResult(
                True,
                self.name,
                "SUPPORTED",
                "W25Q64 detected on Raspberry Pi SPI1.",
                {
                    "jedec": jedec.hex(),
                    "unique_id": unique_id.hex(),
                    "physical_uid": unique_id.hex(),
                    "target_id": self._target_id(unique_id),
                    "logical_target_id": logical_id,
                    "metadata_valid": bool(metadata),
                    "metadata": metadata,
                    "flash_size": config.acquisition.rpi_w25q64_size_bytes,
                    "spi_device": f"/dev/spidev{config.acquisition.rpi_spi_bus}.{config.acquisition.rpi_spi_device}",
                    "probe_duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
        except Exception as exc:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", f"Raspberry Pi SPI probe failed: {exc}")
        finally:
            if spi is not None:
                try:
                    spi.close()
                except Exception:
                    pass

    def acquire(self, target: dict, progress: Optional[Callable[[int, int, str], None]] = None) -> AcquisitionResult:
        probe = self.probe(target)
        if not probe.supported:
            return probe

        size = int(probe.metadata["flash_size"])
        logical_target_id = str(probe.metadata["logical_target_id"])
        physical_uid = str(probe.metadata["physical_uid"])
        slot = int(target.get("stm32_slot", target.get("slot", config.acquisition.rpi_stm32_slot)))
        spi = None
        image_path: Optional[Path] = None
        try:
            if not stm32_link.ensure_connected():
                raise STM32ProtocolError(stm32_link.last_error or "STM32 not connected")
            spi = self._open()
            from tempfile import NamedTemporaryFile
            with NamedTemporaryFile(prefix="fivsed-w25q64-", suffix=".bin", delete=False) as tmp:
                image_path = Path(tmp.name)

            with image_path.open("wb") as out:
                processed = 0
                while processed < size:
                    chunk = min(READ_CHUNK, size - processed)
                    addr = processed
                    request = [
                        CMD_READ_DATA,
                        (addr >> 16) & 0xFF,
                        (addr >> 8) & 0xFF,
                        addr & 0xFF,
                    ] + [0x00] * chunk
                    reply = bytes(spi.xfer2(request))
                    if len(reply) != chunk + 4:
                        raise IOError(f"W25Q64 read returned {len(reply)-4} data bytes; expected {chunk}")
                    data = reply[4:]
                    out.write(data)
                    processed += len(data)
                    if progress:
                        progress(processed, size, "ACQUIRING_FIRMWARE")

            if image_path.stat().st_size != size:
                raise IOError("W25Q64 acquisition size does not match expected 8 MiB")

            if progress:
                progress(0, size, "STREAMING_TO_STM32")
            result = stm32_link.stream_file(
                image_path,
                slot,
                logical_target_id,
                physical_id=physical_uid,
                progress=progress,
            )
            result["acquisition_method"] = self.name
            result["source_device_id"] = target.get("id")
            result["target_identity_source"] = "W25Q64_FACTORY_UNIQUE_ID_READ_BY_RASPBERRY_PI"
            result["physical_uid"] = physical_uid
            result["logical_target_id"] = logical_target_id
            return AcquisitionResult(
                True,
                self.name,
                str(result.get("result", "READ_ERROR")),
                str(result.get("reason", "")),
                metadata=result,
            )
        except (OSError, STM32ProtocolError, RuntimeError) as exc:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_ERROR", str(exc) or "W25Q64 acquisition failed")
        finally:
            if spi is not None:
                try:
                    spi.close()
                except Exception:
                    pass
            if image_path is not None:
                try:
                    image_path.unlink(missing_ok=True)
                except OSError:
                    pass
