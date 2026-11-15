from .base import FirmwareAcquisitionProvider, AcquisitionResult
from .spi_flash import SPIFlashProvider
from .rpi_w25q64 import RPiW25Q64Provider
from .serial_target import AuthorizedSerialProvider
from .usb_storage import USBStorageProvider
from .esp32_flash import ESP32FlashProvider
from .unsupported import UnsupportedProvider

__all__ = [
    "FirmwareAcquisitionProvider",
    "AcquisitionResult",
    "SPIFlashProvider",
    "RPiW25Q64Provider",
    "AuthorizedSerialProvider",
    "USBStorageProvider",
    "ESP32FlashProvider",
    "UnsupportedProvider",
]
