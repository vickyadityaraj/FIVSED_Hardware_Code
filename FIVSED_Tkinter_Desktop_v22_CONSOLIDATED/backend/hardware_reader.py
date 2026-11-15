from __future__ import annotations

import time

from .device_discovery import discover_host_devices
from .config import config
from .stm32_link import stm32_link, STM32ProtocolError
from .storage import storage
from .acquisition.rpi_w25q64 import RPiW25Q64Provider


class HardwareTargetReader:
    """Runtime target discovery and capability classification.

    The Raspberry Pi W25Q64 path is the current physical demonstration path:
    Pi reads raw bytes and forwards them to STM32. Target metadata is parsed for
    operator display only. STM32 remains authoritative for SHA-256/reference
    comparison. The W25Q64 factory UID is retained separately as physical
    hardware evidence; the embedded SERIAL/UUID is only a logical display ID.
    """

    def __init__(self) -> None:
        self._last_ids: set[str] = set()
        self._rpi_w25q64 = RPiW25Q64Provider()

    @staticmethod
    def _reference_map(status: dict) -> tuple[dict[str, dict], list[int]]:
        by_target: dict[str, dict] = {}
        free_slots: list[int] = []
        for item in status.get("slots", []) if isinstance(status, dict) else []:
            try:
                slot = int(item.get("slot", -1))
            except (TypeError, ValueError):
                slot = -1
            target_id = str(item.get("target_id") or "").strip()
            if target_id and bool(item.get("registered")):
                by_target[target_id] = dict(item)
            if 0 <= slot <= 3 and not bool(item.get("registered")):
                free_slots.append(slot)
        return by_target, free_slots

    def detect_connected_targets(self) -> list[dict]:
        targets: list[dict] = []
        stm32_status: dict = {}

        # If STM32 is connected, obtain its authoritative reference-slot state.
        # This call is also the primary connection probe for the USB CDC safety core.
        if stm32_link.ensure_connected():
            try:
                stm32_status = stm32_link.status()
            except STM32ProtocolError:
                stm32_status = {}

            for slot in stm32_status.get("slots", []) if isinstance(stm32_status, dict) else []:
                if not slot.get("connected"):
                    continue
                targets.append(
                    {
                        "id": slot.get("physical_id") or slot.get("target_id"),
                        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "name": slot.get("model") or slot.get("target_id") or "SPI NOR Target",
                        "friendly_name": slot.get("model") or slot.get("target_id") or "SPI NOR Target",
                        "manufacturer": slot.get("manufacturer", "N/A"),
                        "model": slot.get("model", "N/A"),
                        "type": slot.get("type", "SPI_NOR"),
                        "vid": "N/A",
                        "pid": "N/A",
                        "serial": slot.get("serial", "N/A"),
                        "physical_uid": slot.get("physical_id", "N/A"),
                        "logical_target_id": slot.get("target_id", "N/A"),
                        "bus": "STM32 SPI1",
                        "device_path": f"STM32 SLOT {slot.get('slot', 0) + 1}",
                        "interface": f"STM32-SLOT-{slot.get('slot', 0) + 1}",
                        "status": "CONNECTED",
                        "instance_id": slot.get("physical_id") or slot.get("target_id"),
                        "acquisition_method": slot.get("acquisition_method", "UNSUPPORTED"),
                        "capability": slot.get("capability", "ACQUISITION_UNSUPPORTED"),
                        "firmware_access": slot.get("firmware_access", "UNKNOWN"),
                        "jedec": slot.get("jedec", "N/A"),
                        "firmware_size": slot.get("firmware_size"),
                        "slot": slot.get("slot", 0),
                        "stm32_slot": slot.get("slot", 0),
                        "registered": bool(slot.get("registered", False)),
                    }
                )

        registered_by_target, free_slots = self._reference_map(stm32_status)

        # DEFAULT FIVSED TARGET: real W25Q64 connected directly to Raspberry Pi SPI1 CE0.
        w25q64_target = {
            "id": "rpi-w25q64-spi1",
            "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "name": "W25Q64 Target",
            "friendly_name": "W25Q64 Target (Raspberry Pi SPI1)",
            "manufacturer": "Winbond",
            "model": "W25Q64JV",
            "type": "SPI_NOR",
            "vid": "N/A",
            "pid": "N/A",
            "serial": "N/A",
            "physical_uid": "N/A",
            "logical_target_id": "N/A",
            "bus": f"Raspberry Pi SPI{config.acquisition.rpi_spi_bus}",
            "device_path": f"/dev/spidev{config.acquisition.rpi_spi_bus}.{config.acquisition.rpi_spi_device}",
            "interface": f"RPI-SPI{config.acquisition.rpi_spi_bus}-CE{config.acquisition.rpi_spi_device}",
            "status": "CONNECTED",
            "instance_id": "rpi-w25q64-spi1",
            "acquisition_method": "RPI_W25Q64_SPI",
            "capability": "CAPABILITY_PROBE",
            "firmware_access": "READABLE_IF_W25Q64_PRESENT",
            "slot": config.acquisition.rpi_stm32_slot,
            "stm32_slot": config.acquisition.rpi_stm32_slot,
            "registered": False,
        }
        try:
            probe = self._rpi_w25q64.probe(w25q64_target)
            if probe.supported:
                metadata = dict(probe.metadata.get("metadata") or {})
                logical_id = str(probe.metadata.get("logical_target_id") or "")
                physical_uid = str(probe.metadata.get("physical_uid") or "")
                physical_target_id = str(probe.metadata.get("target_id") or "")
                ref = registered_by_target.get(logical_id)

                if ref is not None:
                    stm_slot = int(ref.get("slot", config.acquisition.rpi_stm32_slot))
                elif free_slots:
                    stm_slot = free_slots[0]
                else:
                    stm_slot = int(config.acquisition.rpi_stm32_slot)

                product = metadata.get("PRODUCT") or "W25Q64JV"
                manufacturer = metadata.get("MANUFACTURER") or "Winbond"
                model = product
                w25q64_target.update(
                    {
                        "id": physical_target_id or ("rpi-w25q64-" + physical_uid),
                        "instance_id": physical_target_id or ("rpi-w25q64-" + physical_uid),
                        "name": model,
                        "friendly_name": product,
                        "manufacturer": manufacturer,
                        "model": model,
                        "serial": metadata.get("SERIAL", "N/A"),
                        "physical_uid": physical_uid or "N/A",
                        "logical_target_id": logical_id or "N/A",
                        "bus": f"Raspberry Pi SPI{config.acquisition.rpi_spi_bus}",
                        "slot": stm_slot,
                        "stm32_slot": stm_slot,
                        "capability": "ACQUISITION_SUPPORTED",
                        "firmware_access": "READABLE",
                        "jedec": probe.metadata.get("jedec", "N/A").upper(),
                        "firmware_size": probe.metadata.get("flash_size"),
                        "stm32_target_id": logical_id,
                        "registered": ref is not None,
                        "reference_state": "TRUSTED_REFERENCE_STORED" if ref is not None else "NOT_REGISTERED",
                        "metadata_valid": bool(probe.metadata.get("metadata_valid")),
                        "metadata": metadata,
                        "bios_vendor": metadata.get("BIOS_VENDOR", "N/A"),
                        "bios_version": metadata.get("BIOS_VERSION", "N/A"),
                        "bios_date": metadata.get("BIOS_DATE", "N/A"),
                        "uefi_version": metadata.get("UEFI_VERSION", "N/A"),
                        "architecture": metadata.get("ARCHITECTURE", "N/A"),
                        "cpu": metadata.get("CPU", "N/A"),
                        "sku": metadata.get("SKU", "N/A"),
                        "asset_tag": metadata.get("ASSET_TAG", "N/A"),
                        "uuid": metadata.get("UUID", "N/A"),
                        "build_id": metadata.get("BUILD_ID", "N/A"),
                    }
                )
                storage.record_target_observation(w25q64_target)
                targets.append(w25q64_target)
        except Exception:
            pass

        # Real host devices. Unsupported devices remain visible as detected hardware,
        # but they never receive a fake firmware result. The configured ESP32 USB
        # console is controller infrastructure, not a monitored target.
        for dev in discover_host_devices():
            if dev.get("type") not in ("SERIAL", "REMOVABLE_STORAGE", "USB"):
                continue
            if dev.get("interface", "") == stm32_link.port:
                continue
            if config.serial.esp32_port and dev.get("interface") == config.serial.esp32_port:
                continue
            text = " ".join(str(dev.get(k, "")) for k in (
                "name", "friendly_name", "manufacturer", "model", "vid", "pid",
                "device_path", "usb_device_class", "usb_device_subclass",
            )).lower()
            if (str(dev.get("vid", "")).upper() == "0483" and str(dev.get("pid", "")).upper() == "5740") or "fivsed security core" in text:
                continue
            if dev.get("type") == "USB" and str(dev.get("usb_device_class", "")).strip() == "09":
                continue

            dev = dict(dev)
            vid = str(dev.get("vid") or "").upper()
            is_espressif = vid == "303A" or "espressif" in text or "esp32" in text or "esp8266" in text
            is_android_mtp = (
                dev.get("type") == "USB"
                and ("mtp" in text or "android" in text or "samsung" in text or "google" in text or "xiaomi" in text or "oneplus" in text)
            )

            if is_espressif and dev.get("type") == "SERIAL":
                # The ESP32 is FIVSED's communications/controller processor.
                dev["controller_component"] = "ESP32"
                dev["acquisition_method"] = "ESP32_FLASH_AUTHORIZED"
                dev["capability"] = "CAPABILITY_PROBE"
                dev["firmware_access"] = "BOOTLOADER_READ_IF_AUTHORIZED"
                dev["slot"] = config.acquisition.esp32_stm32_slot
                raw_identity = str(dev.get("serial") if dev.get("serial") not in (None, "", "N/A") else dev.get("id", dev.get("interface", "")))
                dev["stm32_target_id"] = ("esp32:" + raw_identity)[-31:]
            elif is_android_mtp:
                dev["acquisition_method"] = "ANDROID_MTP_DETECTED"
                dev["capability"] = "DEVICE_DETECTED_FIRMWARE_UNSUPPORTED"
                dev["firmware_access"] = "MTP_DEVICE_DETECTED"
            elif dev.get("type") == "REMOVABLE_STORAGE":
                dev["acquisition_method"] = "USB_STORAGE_READONLY"
                dev["capability"] = "CAPABILITY_PROBE"
                dev["firmware_access"] = "READ_ONLY_STORAGE_IF_AUTHORIZED"
            else:
                dev["acquisition_method"] = "UNSUPPORTED"
                dev["capability"] = "DEVICE_DETECTED_FIRMWARE_UNSUPPORTED"
                dev["firmware_access"] = "DEVICE_DETECTED_NO_AUTHORIZED_FIRMWARE_PATH"

            if dev.get("type") == "SERIAL":
                dev["name"] = dev.get("name") or dev.get("friendly_name") or dev.get("interface", "Serial device")
            elif dev.get("type") == "USB":
                dev["name"] = dev.get("name") or dev.get("friendly_name") or f"USB Device {vid}:{dev.get('pid', 'N/A')}"
            targets.append(dev)

        current_ids = {str(t.get("id")) for t in targets if t.get("id")}
        connected = sorted(current_ids - self._last_ids)
        disconnected = sorted(self._last_ids - current_ids)
        for target_id in connected:
            target = next((t for t in targets if t.get("id") == target_id), None)
            if target:
                storage.record_target_observation(target)
                storage.add_log("INFO", "DISCOVERY", f"Target connected: {target.get('name', target_id)}")
        for target_id in disconnected:
            previous = storage.get_target_observations()
            target = next((t for t in previous if t.get("id") == target_id), None)
            storage.add_log("INFO", "DISCOVERY", f"Target disconnected: {target.get('name', target_id) if target else target_id}")
        self._last_ids = current_ids
        return targets


hardware_reader = HardwareTargetReader()
