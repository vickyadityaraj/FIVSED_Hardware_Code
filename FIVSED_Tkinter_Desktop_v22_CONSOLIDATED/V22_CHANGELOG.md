# FIVSED v22 consolidated changes

## Communication and trust boundary

- Replaced the old STM32->ESP32-only UART implementation with a true bidirectional PA9/PA10 <-> GPIO16/17 UART link at 115200 8N1.
- Added a framed ESP32->STM32 heartbeat with CRC16 and STM32-side parser/state timeout.
- Added STM32 authenticated `ESP32_HEARTBEAT_ACK` containing `ACK: ESP32_ACTIVE`.
- STM32 component heartbeats now report real Pi and ESP32 liveness.
- ESP32 liveness on the Pi GUI is derived from the STM32-observed heartbeat when STM32 is connected; USB ESP32 probing remains a development fallback only.
- ESP32 uploads only STM32-originated `FIRMWARE_VERIFICATION` events, preserving the original JSON body and HMAC.

## STM32 reference identity

- STM32 reference slots retain the logical target ID and physical W25Q64 factory UID separately.
- Added a safe migration path for the previously shipped v1 reference table; existing reference digests are not silently discarded.
- Pi selects the STM32 slot before scans/streams so physical REGISTER/RE-BASELINE actions apply to the selected target.
- Hashes remain internal to STM32 and are never displayed by the Tkinter UI.

## Raspberry Pi W25Q64 target

- W25Q64 provider reads `FIVSED-META` at offset `0x1000`.
- Target display fields can now include manufacturer, product/model, serial, BIOS/UEFI metadata, CPU, SKU, asset tag, UUID and build ID.
- The physical W25Q64 factory UID remains separate from operator-facing metadata.

## Raspberry Pi appliance/HMI preservation

- Preserved 90-degree LEFT X11 display rotation.
- Added/retained touch coordinate correction matrix `1 0 0 0 -1 1 0 0 1` through a reusable script.
- Preserved GPIO26 shutdown button configuration.
- Preserved GPIO3 wake/power-up button wiring behavior.
- Preserved GPIO13 reboot button as a systemd service.
- Preserved LightDM/Openbox/Tkinter automatic startup.

## Validation

- Python syntax/compile checks are included in `tests/`.
- Protocol framing checks are included in `tests/test_protocol_v22.py`.
- Metadata parsing checks are included in `tests/test_w25q64_metadata.py`.
- STM32 source is also checked with a host-side syntax/stub harness where available; actual ARM/PlatformIO hardware compilation still needs the PlatformIO/ARM toolchain on the user's build machine.
