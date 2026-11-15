from __future__ import annotations

from .base import AcquisitionResult, FirmwareAcquisitionProvider


class USBStorageProvider(FirmwareAcquisitionProvider):
    """Capability placeholder for read-only boot-partition acquisition.

    A deployment-specific file manifest must be defined before this provider can
    be enabled. The default behavior is deliberately unsupported rather than
    reading arbitrary storage and calling it firmware.
    """

    name = "USB_STORAGE_READONLY"

    def probe(self, target: dict) -> AcquisitionResult:
        return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "Read-only storage was detected, but no authorized firmware file manifest is configured.")

    def acquire(self, target: dict, progress=None) -> AcquisitionResult:
        return self.probe(target)
