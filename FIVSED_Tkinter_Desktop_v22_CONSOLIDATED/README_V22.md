# FIVSED v22 — consolidated Raspberry Pi / STM32 / ESP32 release

This package consolidates the working FIVSED Raspberry Pi appliance with the v22 bidirectional STM32↔ESP32 communication contract and W25Q64 metadata display.

## Fixed architecture

```text
TARGET W25Q64
      ↓ SPI
Raspberry Pi 3B+
      ↓ USB CDC
STM32F411CEU6  ← sole security authority
      ↕ UART 115200 8N1
ESP32           ← Wi-Fi/HTTPS telemetry + actuator gateway
      ↓ Wi-Fi / HTTPS
Web application
```

## STM32 build

The supported STM32 source is the complete `stm32/` PlatformIO project in this package.

The project uses Arduino/STM32duino with native USB CDC for the Raspberry Pi link and direct STM32F411 registers for the W25Q64 SPI and ESP32 UART. Build/flash it with PlatformIO on a machine that has the ARM/STM32 PlatformIO toolchain.

```bash
cd stm32
pio run
pio run -t upload
```

Use an ST-Link for upload. USB CDC then exposes the STM32 safety core to the Raspberry Pi as a USB serial device (normally `/dev/ttyACM*`).

## STM32 <-> ESP32 wiring

```text
STM32 PA9  TX  ->  ESP32 GPIO16 RX
STM32 PA10 RX  <-  ESP32 GPIO17 TX
STM32 GND      --  ESP32 GND

115200, 8N1
```

The reverse ESP32 heartbeat uses a separate framed control direction. STM32 answers it with an authenticated `ESP32_HEARTBEAT_ACK` containing `ACK: ESP32_ACTIVE`.

## Raspberry Pi W25Q64 wiring

```text
W25Q64 VCC  -> Pi 3.3V physical pin 17
W25Q64 GND  -> Pi GND physical pin 25
W25Q64 CS   -> GPIO18 / physical pin 12
W25Q64 DO   -> GPIO19 / physical pin 35
W25Q64 SCLK -> GPIO21 / physical pin 40
W25Q64 DI   -> GPIO20 / physical pin 38
```

The Pi provider uses `/dev/spidev1.0`, SPI mode 0, 4 MHz, and an 8 MiB acquisition size.

## W25Q64 metadata

The demo firmware images contain a synthetic `FIVSED-META` block at offset `0x1000`. v22 parses it for operator display. The real W25Q64 factory unique ID is retained separately as physical hardware evidence.

The metadata is presentation data and is not a trust source. STM32's internal reference table and SHA-256 comparison remain authoritative.

## Raspberry Pi HMI preservation

- X11 90-degree LEFT rotation through `rotate-display-left.sh`.
- Touch correction through `fivsed-touch-correction.sh` with matrix `1 0 0 0 -1 1 0 0 1`.
- GPIO26 shutdown button (pin 37 -> GND pin 39) using the existing gpio-shutdown overlay.
- GPIO3 wake/power-up button (pin 5 -> GND pin 6).
- GPIO13 reboot button (pin 33 -> GND pin 34) using the included systemd service.
- LightDM/Openbox automatic graphical login and Tkinter application startup.

See `pi-appliance/README.md` and `setup-tkinter-desktop.sh`.

## Important security behavior

The Raspberry Pi does not calculate or store the trusted reference hash. ESP32 does not calculate or hold the trusted reference. Security-changing reference operations remain physically authorized on STM32.

The desktop GUI intentionally does not display the raw SHA-256 digest.

## Validation performed for this package

- Python syntax compilation: completed successfully.
- Python unit tests: `3 passed`.
- STM32 C sources: host-side `clang -fsyntax-only` completed successfully (the pointer-cast warnings are artifacts of compiling fixed STM32 MMIO addresses on a 64-bit host, not STM32 target build errors).
- STM32 C++ source syntax: host-side `clang++ -fsyntax-only` completed; the same fixed-address host warnings apply to direct-register code.
- Actual ARM/PlatformIO link-and-flash was not performed in this build environment because PlatformIO and the ARM cross toolchain are not installed here. Perform the final `pio run` on the development machine before flashing hardware.
