# FIVSED — Firmware Integrity Verification and Security Event Detection

**FIVSED** is an embedded security appliance and verification architecture designed to perform out-of-band firmware integrity checks and cryptographic verification for connected target microcontrollers and flash devices.

---

## Architecture Overview

```text
+---------------------+           +------------------------+
| Winbond W25Q64      |   SPI1    | Raspberry Pi 3B+       |
| SPI NOR Flash       | --------> | (Acquisition & GUI)    |
+---------------------+           +-----------+------------+
                                              | Native USB CDC
                                              v (/dev/ttyACM*)
+---------------------+  UART 115k +------------------------+
| ESP32 Gateway       | <--------> | STM32F411CEU6          |
| (HTTPS / Telemetry) |    8N1     | (Sole Security Core)   |
+---------------------+           +------------------------+
```

1. **Target Chip (Winbond W25Q64)**: Connected to Raspberry Pi via high-speed SPI1. Contains the firmware image to be validated.
2. **Raspberry Pi 3B+ (Operator Appliance)**: Acquires raw firmware over SPI, displays the touch-friendly portrait GUI (480x800), and streams chunks over native USB CDC to STM32. Does **not** compute or store reference hashes.
3. **STM32F411CEU6 ("Black Pill") (Root of Security Authority)**: Sole integrity decision authority. Incrementally computes SHA-256 over incoming USB CDC stream, compares against trusted references in internal Flash Sector 7 (`0x08060000`), requires physical button presses to register/update references, and triggers tamper alerts.
4. **ESP32 (Telemetry & Actuator Gateway)**: Bi-directional UART link with STM32 (HMAC-SHA256 verified frames) forwarding status events to the cloud web application over Wi-Fi / HTTPS.

---

## Guides & Documentation

- 📖 **[Raspberry Pi Installation Guide](RASPBERRY_PI_INSTALLATION_GUIDE.md)**: Full terminal commands, `.sh` execution, autologin, X11 rotation, touch calibration, and systemd service setup.
- 🛠️ **[STM32 Configuration & Programming Guide](STM32_CONFIGURATION_AND_PROGRAMMING_GUIDE.md)**: CubeMX pinout configuration, Clock tree setup, CubeIDE build steps, and ST-Link / DFU flashing steps.
- 📋 **[Communication Contract v22](FIVSED_Tkinter_Desktop_v22_CONSOLIDATED/COMMUNICATION_CONTRACT_V22.md)**: Protocol frame specifications (Pi `0xF5`, ESP32 `0x5A` / `0xA5`), HMAC signatures, and message timings.
- 🔌 **[W25Q64 Default Target Wiring](FIVSED_Tkinter_Desktop_v22_CONSOLIDATED/RPI_W25Q64_DEFAULT_TARGET.md)**: Detailed wiring diagrams for the Winbond W25Q64 flash breakout to Raspberry Pi SPI1.

---

## Repository Structure

```text
FIVSED_Hardware_Code/
├── README.md                                    # Top-level project documentation
├── RASPBERRY_PI_INSTALLATION_GUIDE.md           # Master Raspberry Pi setup instructions
├── STM32_CONFIGURATION_AND_PROGRAMMING_GUIDE.md # Master STM32 CubeMX / IDE / Flashing guide
└── FIVSED_Tkinter_Desktop_v22_CONSOLIDATED/      # Consolidated appliance package
    ├── setup-tkinter-desktop.sh                 # Master Pi OS & desktop setup script
    ├── start-fivsed.sh                          # Pi GUI launcher script
    ├── rotate-display-left.sh                   # X11 display rotation (90° left)
    ├── fivsed-touch-correction.sh               # Touch coordinate matrix transformation
    ├── requirements.txt                         # Python dependencies
    ├── backend/                                 # Acquisition engine, Flask API, STM32 link
    │   ├── acquisition/                         # Hardware providers (W25Q64 SPI1, ESP32, etc.)
    │   ├── stm32_link.py                        # Binary framing protocol over USB CDC
    │   ├── stm32_engine.py                      # Scan execution coordinator
    │   └── hardware_reader.py                   # Target detection manager
    ├── gui/                                     # Fullscreen portrait Tkinter console
    │   └── main.py                              # Desktop operator interface
    ├── pi-appliance/                            # Physical buttons & systemd services
    │   ├── fivsed-reboot-button.py              # GPIO 13 hardware reboot daemon
    │   └── install-reboot-button.sh             # Reboot button service installer
    ├── STM32/                                   # STM32 security core project
    │   └── fivsed_v2/                           # STM32CubeMX / STM32CubeIDE project
    │       ├── fivsed_v2.ioc                    # CubeMX project file (F411CEU6)
    │       ├── Core/Src/main.c                  # SHA-256 engine, protocol, Sector 7 flash
    │       └── USB_DEVICE/                      # USB CDC class driver implementation
    ├── esp32/                                   # ESP32 gateway PlatformIO project
    └── tests/                                   # Unit tests for protocol & metadata
```
