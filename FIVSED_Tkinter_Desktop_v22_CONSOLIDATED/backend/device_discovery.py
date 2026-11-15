from __future__ import annotations

import glob
import json
import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def _clean(value: Any) -> str:
    if value is None:
        return "N/A"
    value = str(value).strip()
    return value or "N/A"


def _parse_vid_pid(value: str) -> tuple[str, str]:
    vid = pid = "N/A"
    m = re.search(r"VID_([0-9A-Fa-f]{4})", value or "")
    if m:
        vid = m.group(1).upper()
    m = re.search(r"PID_([0-9A-Fa-f]{4})", value or "")
    if m:
        pid = m.group(1).upper()
    return vid, pid


def _linux_sysfs_value(path: Path, name: str) -> str:
    try:
        return _clean((path / name).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return "N/A"


def _usb_ancestor(sys_device: Path) -> Path | None:
    current = sys_device.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "idVendor").exists() and (candidate / "idProduct").exists():
            return candidate
    return None


def _linux_serial_devices() -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    except Exception:
        ports = []

    for port in ports:
        device_path = Path(port.device)
        tty_name = device_path.name
        sys_tty = Path("/sys/class/tty") / tty_name / "device"
        usb = _usb_ancestor(sys_tty) if sys_tty.exists() else None
        vid = f"{port.vid:04X}" if getattr(port, "vid", None) is not None else "N/A"
        pid = f"{port.pid:04X}" if getattr(port, "pid", None) is not None else "N/A"
        manufacturer = _clean(getattr(port, "manufacturer", None))
        product = _clean(getattr(port, "product", None))
        serial = _clean(getattr(port, "serial_number", None))
        interface = _clean(getattr(port, "interface", None))

        if usb:
            vid = _linux_sysfs_value(usb, "idVendor") if vid == "N/A" else vid
            pid = _linux_sysfs_value(usb, "idProduct") if pid == "N/A" else pid
            manufacturer = _linux_sysfs_value(usb, "manufacturer") if manufacturer == "N/A" else manufacturer
            product = _linux_sysfs_value(usb, "product") if product == "N/A" else product
            serial = _linux_sysfs_value(usb, "serial") if serial == "N/A" else serial
            bus = _linux_sysfs_value(usb, "busnum")
            devnum = _linux_sysfs_value(usb, "devnum")
            device_path_text = str(usb)
        else:
            bus = "N/A"
            devnum = "N/A"
            device_path_text = str(sys_tty)

        instance_id = _clean(getattr(port, "hwid", None))
        stable_seed = serial if serial != "N/A" else (instance_id if instance_id != "N/A" else f"{vid}:{pid}:{device_path_text}")
        stable_id = f"linux-serial-{stable_seed}"

        devices.append(
            {
                "id": stable_id,
                "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "name": _clean(product if product != "N/A" else getattr(port, "description", None)),
                "friendly_name": _clean(getattr(port, "description", None)),
                "manufacturer": manufacturer,
                "model": product,
                "type": "SERIAL",
                "vid": vid,
                "pid": pid,
                "serial": serial,
                "bus": bus,
                "devnum": devnum,
                "device_path": device_path_text,
                "interface": port.device,
                "status": "CONNECTED",
                "instance_id": instance_id,
            }
        )
    return devices


def _windows_pnp_devices() -> list[dict[str, Any]]:
    """Enumerate present Windows PnP devices using the native PnpDevice module.

    Get-PnpDevice -PresentOnly reports devices physically present. A CIM fallback keeps
    development usable on Windows editions where the PnpDevice PowerShell module is absent.
    """
    native_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-PnpDevice -PresentOnly |
  Select-Object Status,Class,FriendlyName,InstanceId,Manufacturer,ProblemCode |
  ConvertTo-Json -Compress
"""
    fallback_script = r"""
$items = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'OK' }
$items | Select-Object Name,Manufacturer,PNPDeviceID,Status,Service,ClassGuid,Description | ConvertTo-Json -Compress
"""

    def run(script: str) -> list[dict[str, Any]]:
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return []
            payload = json.loads(proc.stdout)
            if isinstance(payload, dict):
                payload = [payload]
            return payload if isinstance(payload, list) else []
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            return []

    payload = run(native_script)
    native = bool(payload)
    if not native:
        payload = run(fallback_script)

    result: list[dict[str, Any]] = []
    for item in payload:
        if native:
            pnp = _clean(item.get("InstanceId"))
            name = _clean(item.get("FriendlyName"))
            friendly = name
            status = _clean(item.get("Status"))
            device_class = _clean(item.get("Class"))
            manufacturer = _clean(item.get("Manufacturer"))
            problem = _clean(item.get("ProblemCode"))
            service = "N/A"
        else:
            pnp = _clean(item.get("PNPDeviceID"))
            name = _clean(item.get("Name"))
            friendly = _clean(item.get("Description") if item.get("Description") else name)
            status = _clean(item.get("Status"))
            device_class = _clean(item.get("ClassGuid"))
            manufacturer = _clean(item.get("Manufacturer"))
            problem = "N/A"
            service = _clean(item.get("Service"))

        vid, pid = _parse_vid_pid(pnp)
        text = f"{name} {friendly} {manufacturer} {pnp} {device_class}".lower()
        is_usb = pnp.lower().startswith("usb\\")
        is_relevant = is_usb or any(token in text for token in ("com", "usb", "storage", "disk", "serial", "uart", "esp32", "espressif"))
        if not is_relevant:
            continue
        result.append(
            {
                "id": f"windows-pnp-{pnp}",
                "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "name": name,
                "friendly_name": friendly,
                "manufacturer": manufacturer,
                "model": name,
                "type": device_class,
                "vid": vid,
                "pid": pid,
                "serial": "N/A",
                "bus": "USB" if is_usb else "N/A",
                "devnum": "N/A",
                "device_path": pnp,
                "interface": "N/A",
                "status": "CONNECTED" if status.upper() in {"OK", "CONNECTED", "N/A"} else status.upper(),
                "instance_id": pnp,
                "service": service,
                "problem_code": problem,
            }
        )
    return result


def _windows_serial_devices() -> list[dict[str, Any]]:
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    except Exception:
        ports = []

    devices: list[dict[str, Any]] = []
    for port in ports:
        hwid = _clean(getattr(port, "hwid", None))
        vid = f"{port.vid:04X}" if getattr(port, "vid", None) is not None else "N/A"
        pid = f"{port.pid:04X}" if getattr(port, "pid", None) is not None else "N/A"
        serial = _clean(getattr(port, "serial_number", None))
        stable_seed = serial if serial != "N/A" else (hwid if hwid != "N/A" else port.device)
        devices.append(
            {
                "id": f"windows-serial-{stable_seed}",
                "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "name": _clean(getattr(port, "description", None)),
                "friendly_name": _clean(getattr(port, "description", None)),
                "manufacturer": _clean(getattr(port, "manufacturer", None)),
                "model": _clean(getattr(port, "product", None)),
                "type": "SERIAL",
                "vid": vid,
                "pid": pid,
                "serial": serial,
                "bus": "N/A",
                "devnum": "N/A",
                "device_path": hwid,
                "interface": port.device,
                "status": "CONNECTED",
                "instance_id": hwid,
            }
        )
    return devices



def _linux_usb_devices() -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    root = Path("/sys/bus/usb/devices")
    if not root.exists():
        return devices
    for entry in sorted(root.iterdir()):
        if not (entry / "idVendor").exists() or not (entry / "idProduct").exists():
            continue
        vid = _linux_sysfs_value(entry, "idVendor")
        pid = _linux_sysfs_value(entry, "idProduct")
        manufacturer = _linux_sysfs_value(entry, "manufacturer")
        product = _linux_sysfs_value(entry, "product")
        serial = _linux_sysfs_value(entry, "serial")
        bus = _linux_sysfs_value(entry, "busnum")
        devnum = _linux_sysfs_value(entry, "devnum")
        instance_id = str(entry.resolve())
        stable_seed = serial if serial != "N/A" else f"{vid}:{pid}:{entry.name}"
        device_class = _linux_sysfs_value(entry, "bDeviceClass")
        subclass = _linux_sysfs_value(entry, "bDeviceSubClass")
        protocol = _linux_sysfs_value(entry, "bDeviceProtocol")
        devices.append({
            "id": f"linux-usb-{stable_seed}",
            "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "name": product,
            "friendly_name": product,
            "manufacturer": manufacturer,
            "model": product,
            "type": "USB",
            "vid": vid.upper(),
            "pid": pid.upper(),
            "serial": serial,
            "bus": bus,
            "devnum": devnum,
            "device_path": str(entry),
            "interface": "N/A",
            "status": "CONNECTED",
            "instance_id": instance_id,
            "usb_device_class": device_class,
            "usb_device_subclass": subclass,
            "usb_device_protocol": protocol,
        })
    return devices

def _linux_storage_devices() -> list[dict[str, Any]]:
    cmd = [
        "lsblk",
        "-J",
        "-o",
        "NAME,KNAME,TYPE,RM,RO,FSTYPE,LABEL,UUID,VENDOR,MODEL,SERIAL,TRAN,MOUNTPOINTS",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    result: list[dict[str, Any]] = []
    for dev in data.get("blockdevices", []):
        for child in dev.get("children", []) or []:
            tran = _clean(child.get("tran") or dev.get("tran"))
            rm = str(child.get("rm", dev.get("rm", "0")))
            if tran.lower() != "usb" and rm != "1":
                continue
            name = _clean(child.get("name"))
            path = "/dev/" + name if name != "N/A" else "N/A"
            stable_seed = _clean(child.get("uuid") or child.get("serial") or path)
            result.append(
                {
                    "id": f"linux-storage-{stable_seed}",
                    "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "name": _clean(child.get("label") or child.get("model") or name),
                    "friendly_name": _clean(child.get("label") or child.get("model") or name),
                    "manufacturer": _clean(child.get("vendor") or dev.get("vendor")),
                    "model": _clean(child.get("model") or dev.get("model")),
                    "type": "REMOVABLE_STORAGE",
                    "vid": "N/A",
                    "pid": "N/A",
                    "serial": _clean(child.get("serial") or dev.get("serial")),
                    "bus": tran,
                    "devnum": "N/A",
                    "device_path": path,
                    "interface": path,
                    "status": "CONNECTED",
                    "instance_id": stable_seed,
                    "filesystem": _clean(child.get("fstype")),
                    "mountpoints": child.get("mountpoints") or [],
                    "read_only": str(child.get("ro", dev.get("ro", "0"))) == "1",
                }
            )
    return result


def linux_host_devices() -> list[dict[str, Any]]:
    serial_devices = _linux_serial_devices()
    usb_devices = _linux_usb_devices()
    serial_identity = {(d.get("vid"), d.get("pid"), d.get("serial")) for d in serial_devices
                       if d.get("vid") != "N/A" or d.get("pid") != "N/A"}
    usb_devices = [
        d for d in usb_devices
        if not (d.get("serial") != "N/A" and (d.get("vid"), d.get("pid"), d.get("serial")) in serial_identity)
    ]
    return serial_devices + usb_devices + _linux_storage_devices()


def windows_host_devices() -> list[dict[str, Any]]:
    devices = _windows_serial_devices()
    pnp = _windows_pnp_devices()
    seen = {d["interface"] for d in devices if d.get("interface") != "N/A"}
    for item in pnp:
        interface = item.get("interface")
        if interface != "N/A" and interface in seen:
            continue
        devices.append(item)
    return devices


_host_cache_lock = threading.RLock()
_host_cache_at = 0.0
_host_cache: list[dict[str, Any]] = []
_HOST_CACHE_TTL = 2.0

def discover_host_devices() -> list[dict[str, Any]]:
    global _host_cache_at, _host_cache
    now = time.monotonic()
    with _host_cache_lock:
        if now - _host_cache_at < _HOST_CACHE_TTL:
            return [dict(item) for item in _host_cache]
        devices = windows_host_devices() if os.name == "nt" else linux_host_devices()
        _host_cache = [dict(item) for item in devices]
        _host_cache_at = now
        return [dict(item) for item in _host_cache]


def available_spi_interfaces() -> list[str]:
    if os.name == "nt":
        return []
    return sorted(glob.glob("/dev/spidev*"))


def available_serial_interfaces() -> list[str]:
    if os.name == "nt":
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") + ["/dev/serial0"] if os.path.exists("/dev/serial0") else glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
