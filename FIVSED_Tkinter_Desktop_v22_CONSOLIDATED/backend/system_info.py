from __future__ import annotations

import glob
import os
import platform
import socket
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _temperature() -> float | None:
    candidates = [Path("/sys/class/thermal/thermal_zone0/temp")]
    if psutil is not None:
        try:
            temps = psutil.sensors_temperatures(fahrenheit=False)
            for entries in temps.values():
                for entry in entries:
                    if getattr(entry, "current", None) is not None:
                        return float(entry.current)
        except Exception:
            pass
    for path in candidates:
        try:
            raw = path.read_text().strip()
            value = float(raw)
            return value / 1000.0 if value > 200 else value
        except (OSError, ValueError):
            continue
    return None


def _uptime() -> str:
    try:
        total = int(float(Path("/proc/uptime").read_text().split()[0]))
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        return f"{days}d {hours}h {minutes}m {secs}s"
    except Exception:
        return "N/A"


def _platform_name() -> str:
    if os.name == "nt":
        return "WINDOWS"
    try:
        model = Path("/proc/device-tree/model").read_text(errors="ignore").strip().replace("\x00", "")
        if "Raspberry Pi" in model:
            return "RASPBERRY PI"
    except OSError:
        pass
    return "LINUX"


def get_system_info() -> dict:
    data = {
        "platform": _platform_name(),
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "model": "N/A",
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count() or 1,
        "cpu_load_percent": None,
        "memory_total_mb": None,
        "memory_available_mb": None,
        "disk_total_gb": None,
        "disk_free_gb": None,
        "temperature_c": _temperature(),
        "serial_interfaces": sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")) if os.name != "nt" else [],
        "spi_interfaces": sorted(glob.glob("/dev/spidev*")) if os.name != "nt" else [],
        "storage_devices": sorted(glob.glob("/dev/sd*") + glob.glob("/dev/nvme*") + glob.glob("/dev/mmcblk*")) if os.name != "nt" else [],
        "uptime": _uptime(),
    }
    try:
        model = Path("/proc/device-tree/model").read_text(errors="ignore").strip().replace("\x00", "")
        if model:
            data["model"] = model
    except OSError:
        pass
    if psutil is not None:
        try:
            data["cpu_load_percent"] = round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            pass
        try:
            mem = psutil.virtual_memory()
            data["memory_total_mb"] = round(mem.total / (1024 * 1024), 1)
            data["memory_available_mb"] = round(mem.available / (1024 * 1024), 1)
        except Exception:
            pass
        try:
            usage = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
            data["disk_total_gb"] = round(usage.total / (1024**3), 2)
            data["disk_free_gb"] = round(usage.free / (1024**3), 2)
        except Exception:
            pass
    return data
