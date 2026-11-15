from __future__ import annotations

from .device_discovery import available_serial_interfaces, available_spi_interfaces, discover_host_devices
from .system_info import get_system_info


def get_pi_status() -> dict:
    info = get_system_info()
    return {
        "platform": info["platform"],
        "hostname": info["hostname"],
        "os": info["os"],
        "kernel": info["kernel"],
        "architecture": info["architecture"],
        "model": info["model"],
        "cpu": info["cpu"],
        "cpu_count": info["cpu_count"],
        "cpu_load_percent": info["cpu_load_percent"],
        "memory_total_mb": info["memory_total_mb"],
        "memory_available_mb": info["memory_available_mb"],
        "disk_total_gb": info["disk_total_gb"],
        "disk_free_gb": info["disk_free_gb"],
        "temperature_c": info["temperature_c"],
        "serial_interfaces": available_serial_interfaces(),
        "spi_interfaces": available_spi_interfaces(),
        "uptime": info["uptime"],
    }


def get_hardware_status() -> dict:
    return {
        "serial": available_serial_interfaces(),
        "spi": available_spi_interfaces(),
        "host_devices": discover_host_devices(),
    }
