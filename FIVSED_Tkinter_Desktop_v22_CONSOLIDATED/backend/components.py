from __future__ import annotations

import time

from .device_discovery import discover_host_devices
from .esp32_link import esp32_link
from .stm32_link import stm32_link
from .storage import storage
from .pi_status import get_pi_status

_last_component_state = {"stm32": None, "esp32": None}


def get_component_status() -> dict:
    """Return the live three-processor status.

    STM32 is authoritative for the STM32<->ESP32 relationship. When STM32 is
    connected, ESP32 status therefore comes from the bidirectional heartbeat
    observed by STM32, not from an unrelated USB-console probe. The USB ESP32
    probe is retained only as a development/provisioning fallback when STM32 is
    unavailable.
    """
    stm = stm32_link.component_status()
    stm32_connected = bool(stm.get("connected"))

    if stm32_connected:
        esp = {
            "connected": bool(stm.get("esp32_active")),
            "transport": "STM32_UART_HEARTBEAT",
            "port": "N/A",
            "last_seen": stm.get("esp32_last_seen"),
            "error": None if stm.get("esp32_active") else "No recent ESP32 heartbeat ACK at STM32",
        }
    else:
        esp = esp32_link.component_status()

    for key, status, name in (("stm32", stm, "STM32"), ("esp32", esp, "ESP32")):
        current = bool(status.get("connected"))
        previous = _last_component_state[key]
        if previous is not None and current != previous:
            storage.add_log("INFO", "COMPONENT", f"{name} {'connected' if current else 'disconnected'}")
        _last_component_state[key] = current

    pi_info = get_pi_status()
    pi = {
        "connected": True,
        "last_seen": time.time(),
        "error": None,
        "platform": pi_info.get("platform"),
        "hostname": pi_info.get("hostname"),
    }
    return {
        "raspberry_pi": pi,
        "stm32": stm,
        "esp32": esp,
        "host_devices": discover_host_devices(),
    }
