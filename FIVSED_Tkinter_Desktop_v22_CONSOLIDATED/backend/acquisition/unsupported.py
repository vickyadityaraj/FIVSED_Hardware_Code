from __future__ import annotations

from .base import AcquisitionResult, FirmwareAcquisitionProvider


class UnsupportedProvider(FirmwareAcquisitionProvider):
    name = "UNSUPPORTED"

    def probe(self, target: dict) -> AcquisitionResult:
        return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "No supported firmware acquisition provider is available for this device.")

    def acquire(self, target: dict, progress=None) -> AcquisitionResult:
        return self.probe(target)
