from __future__ import annotations

from .base import AcquisitionResult, FirmwareAcquisitionProvider
from ..stm32_link import stm32_link


class SPIFlashProvider(FirmwareAcquisitionProvider):
    name = "STM32_SPI_DIRECT"

    def probe(self, target: dict) -> AcquisitionResult:
        if target.get("acquisition_method") != self.name:
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "Target is not an STM32-managed SPI flash slot.")
        if target.get("capability") != "ACQUISITION_SUPPORTED":
            return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "STM32 has not reported a supported SPI flash device.")
        return AcquisitionResult(True, self.name, "SUPPORTED")

    def acquire(self, target: dict, progress=None) -> AcquisitionResult:
        probe = self.probe(target)
        if not probe.supported:
            return probe
        slot = int(target.get("slot", 0))
        result = stm32_link.scan_slot(slot, callback=lambda n, p: progress and progress(int(p.get("bytes_processed", 0)), int(p.get("total_bytes", 0)), p.get("stage", "STREAMING_TO_STM32")))
        status = result.get("result", "READ_ERROR")
        return AcquisitionResult(
            True,
            self.name,
            status,
            str(result.get("reason", "")),
            metadata=result,
        )
