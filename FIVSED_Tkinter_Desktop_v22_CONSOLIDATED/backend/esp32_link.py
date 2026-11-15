from __future__ import annotations

import os
import time
from typing import Optional

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

from .config import config


class ESP32Link:
    """Development/maintenance presence detector for an attached ESP32 USB console.

    The final security UART is one-way STM32 TX -> ESP32 RX. Presence is therefore
    detected locally only when the ESP32 development USB/UART interface is connected.
    """

    def __init__(self) -> None:
        self.last_seen = 0.0
        self.last_error = ""
        self.port: Optional[str] = None

    def _candidate_ports(self) -> list[str]:
        if config.serial.esp32_port:
            return [config.serial.esp32_port]
        if serial is None:
            return []
        try:
            from serial.tools import list_ports
            ports = []
            for p in list_ports.comports():
                text = f"{p.description} {p.manufacturer} {p.product} {p.hwid}".lower()
                if any(token in text for token in ("espressif", "esp32", "cp210", "ch340")):
                    ports.append(p.device)
            return ports
        except Exception:
            return []

    def probe(self) -> bool:
        self.last_error = ""
        if serial is None:
            self.last_error = "pyserial is not installed"
            return False
        for port in self._candidate_ports():
            try:
                with serial.Serial(port, config.serial.esp32_baud, timeout=0.15, write_timeout=0.2) as ser:
                    ser.reset_input_buffer()
                    ser.write(b"STATUS\n")
                    ser.flush()
                    deadline = time.monotonic() + 0.5
                    buf = bytearray()
                    while time.monotonic() < deadline:
                        data = ser.read(128)
                        if data:
                            buf.extend(data)
                            if b"FIVSED_ESP32_READY" in buf or b"FIVSED_ESP32" in buf:
                                self.port = port
                                self.last_seen = time.time()
                                return True
            except Exception as exc:
                self.last_error = f"{port}: {exc}"
        return False

    def component_status(self) -> dict:
        connected = self.probe()
        return {
            "connected": connected,
            "port": self.port or "N/A",
            "last_seen": self.last_seen or None,
            "error": self.last_error or None,
        }


esp32_link = ESP32Link()
