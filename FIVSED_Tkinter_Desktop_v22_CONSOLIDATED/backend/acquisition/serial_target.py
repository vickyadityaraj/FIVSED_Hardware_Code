from __future__ import annotations

from .base import AcquisitionResult, FirmwareAcquisitionProvider


class AuthorizedSerialProvider(FirmwareAcquisitionProvider):
    """Only for target devices that implement a documented, authorized dump protocol.

    The provider intentionally does not guess a serial command. Without an explicit
    protocol implementation from the target vendor/firmware it reports unsupported.
    """

    name = "AUTHORIZED_SERIAL"

    def probe(self, target: dict) -> AcquisitionResult:
        return AcquisitionResult(False, self.name, "FIRMWARE_READ_UNSUPPORTED", "Target serial interface does not expose an authorized FIVSED acquisition protocol.")

    def acquire(self, target: dict, progress=None) -> AcquisitionResult:
        return self.probe(target)
