from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import os

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


@dataclass
class SerialConfig:
    stm32_port: str = ""
    stm32_baud: int = 115200
    esp32_port: str = ""
    esp32_baud: int = 115200
    poll_interval_seconds: float = 3.0


@dataclass
class AcquisitionConfig:
    # Raspberry Pi target SPI path: W25Q64 connected to Pi SPI1 CE0.
    rpi_spi_bus: int = 1
    rpi_spi_device: int = 0
    rpi_spi_speed_hz: int = 4_000_000
    rpi_w25q64_size_bytes: int = 8 * 1024 * 1024
    rpi_stm32_slot: int = 0
    esptool_command: str = ""
    esptool_baud: int = 460800
    max_firmware_bytes: int = 16 * 1024 * 1024
    stream_chunk_bytes: int = 1024
    esp32_stm32_slot: int = 1
    esptool_timeout_seconds: int = 120


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class AppConfig:
    serial: SerialConfig = field(default_factory=SerialConfig)
    acquisition: AcquisitionConfig = field(default_factory=AcquisitionConfig)
    server: ServerConfig = field(default_factory=ServerConfig)


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        raw = {}
    else:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = {}
        except (OSError, ValueError, TypeError):
            raw = {}

    serial_cfg = raw.get("serial", {}) or {}
    acquisition_cfg = raw.get("acquisition", {}) or {}
    server_cfg = raw.get("server", {}) or {}

    return AppConfig(
        serial=SerialConfig(
            stm32_port=str(serial_cfg.get("stm32_port", os.getenv("FIVSED_STM32_PORT", ""))).strip(),
            stm32_baud=max(1200, _safe_int(serial_cfg.get("stm32_baud", os.getenv("FIVSED_STM32_BAUD", 115200)), 115200)),
            esp32_port=str(serial_cfg.get("esp32_port", os.getenv("FIVSED_ESP32_PORT", ""))).strip(),
            esp32_baud=max(1200, _safe_int(serial_cfg.get("esp32_baud", os.getenv("FIVSED_ESP32_BAUD", 115200)), 115200)),
            poll_interval_seconds=max(
                2.0, min(5.0, _safe_float(serial_cfg.get("poll_interval_seconds", 3.0), 3.0))
            ),
        ),
        acquisition=AcquisitionConfig(
            rpi_spi_bus=max(0, _safe_int(acquisition_cfg.get("rpi_spi_bus", 1), 1)),
            rpi_spi_device=max(0, _safe_int(acquisition_cfg.get("rpi_spi_device", 0), 0)),
            rpi_spi_speed_hz=max(500_000, min(20_000_000, _safe_int(acquisition_cfg.get("rpi_spi_speed_hz", 4_000_000), 4_000_000))),
            rpi_w25q64_size_bytes=max(1024 * 1024, min(8 * 1024 * 1024, _safe_int(acquisition_cfg.get("rpi_w25q64_size_bytes", 8 * 1024 * 1024), 8 * 1024 * 1024))),
            rpi_stm32_slot=max(0, min(3, _safe_int(acquisition_cfg.get("rpi_stm32_slot", 0), 0))),
            esptool_command=str(acquisition_cfg.get("esptool_command", os.getenv("FIVSED_ESPTOOL_COMMAND", ""))).strip(),
            esptool_baud=max(9600, _safe_int(acquisition_cfg.get("esptool_baud", os.getenv("FIVSED_ESPTOOL_BAUD", 460800)), 460800)),
            max_firmware_bytes=max(64 * 1024, min(16 * 1024 * 1024, _safe_int(acquisition_cfg.get("max_firmware_bytes", 16 * 1024 * 1024), 16 * 1024 * 1024))),
            stream_chunk_bytes=max(256, min(1024, _safe_int(acquisition_cfg.get("stream_chunk_bytes", 1024), 1024))),
            esp32_stm32_slot=max(0, min(3, _safe_int(acquisition_cfg.get("esp32_stm32_slot", 1), 1))),
            esptool_timeout_seconds=max(30, min(600, _safe_int(acquisition_cfg.get("esptool_timeout_seconds", 120), 120))),
        ),
        server=ServerConfig(
            host=str(server_cfg.get("host", os.getenv("FIVSED_HOST", "127.0.0.1"))).strip() or "127.0.0.1",
            port=max(1, min(65535, _safe_int(server_cfg.get("port", os.getenv("FIVSED_PORT", 8765)), 8765))),
        ),
    )


config = load_config()
