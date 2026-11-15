# FIVSED default target: W25Q64 connected to Raspberry Pi

The default demonstration target is a Winbond W25Q64JV SPI NOR flash connected to Raspberry Pi SPI1 CE0. SPI1 is used so the touchscreen touch controller can keep using its existing SPI path.

## Raspberry Pi 40-pin header

- W25Q64 VCC -> pin 17 (3.3V)
- W25Q64 GND -> pin 25 (GND)
- W25Q64 CLK/SCLK -> pin 40 (GPIO21 / SPI1_SCLK)
- W25Q64 DO -> pin 35 (GPIO19 / SPI1_MISO)
- W25Q64 DI -> pin 38 (GPIO20 / SPI1_MOSI)
- W25Q64 CS -> pin 12 (GPIO18 / SPI1_CE0_N)

The user's six-pin breakout exposes VCC, CS, DO, GND, SCLK and DI only; it does not expose WP/HOLD. Do not apply 5V to the W25Q64.

## Data path

W25Q64 -> Raspberry Pi SPI1 -> raw firmware stream -> STM32 USB CDC -> SHA-256/reference comparison -> result to Pi GUI and ESP32.

The SHA-256 digest is not sent to the Pi GUI or ESP32.

## Metadata path

The v22 Pi provider also reads the optional `FIVSED-META` block at offset `0x1000` for operator-facing device/firmware fields. This metadata is not a trust source; the W25Q64 factory unique ID is kept separately and STM32 remains the integrity authority.
