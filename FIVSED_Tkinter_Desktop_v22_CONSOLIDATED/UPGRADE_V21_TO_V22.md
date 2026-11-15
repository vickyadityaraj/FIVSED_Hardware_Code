# FIVSED v21 -> v22 upgrade

## 1. Back up the working v21 installation

```bash
cp -a ~/FIVSED_GUI ~/FIVSED_GUI.pre-v22-$(date +%Y%m%d-%H%M%S)
```

## 2. Extract v22 and copy over the source

Extract the ZIP so that the directory `FIVSED_Tkinter_Desktop_v22_CONSOLIDATED/` is visible. Then run:

```bash
rsync -a \
  --exclude='.venv/' \
  --exclude='config.json' \
  --exclude='fivsed_data.json' \
  FIVSED_Tkinter_Desktop_v22_CONSOLIDATED/ ~/FIVSED_GUI/
```

This keeps the existing virtual environment, local configuration, and local audit data.

## 3. Update the existing Python environment

```bash
cd ~/FIVSED_GUI
source .venv/bin/activate
pip install -r requirements.txt
```

Do not place Wi-Fi passwords, API keys, or certificates in source files.

## 4. Reapply the Raspberry Pi appliance integration

```bash
cd ~/FIVSED_GUI
chmod +x setup-tkinter-desktop.sh rotate-display-left.sh fivsed-touch-correction.sh
./setup-tkinter-desktop.sh
./pi-appliance/install-reboot-button.sh
```

This preserves/enables:

- 90-degree LEFT X11 display rotation
- portrait touch-coordinate correction
- SPI1 CE0 for the W25Q64
- GPIO26 shutdown button overlay
- LightDM/Openbox/Tkinter autostart
- GPIO13 reboot-button service

The GPIO3 wake/power-up button remains a hardware wake path:
GPIO3 (pin 5) -> button -> GND (pin 6).

Reboot after setup:

```bash
sudo reboot
```

## 5. Flash the new STM32 firmware

The v22 STM32 project is the `stm32/` directory. It is configured for the WeAct/BlackPill STM32F411CEU6 using PlatformIO and the ST-Link upload protocol.

On a machine with PlatformIO installed:

```bash
cd ~/FIVSED_GUI/stm32
pio run
pio run -t upload
```

The v22 UART is full duplex:

```text
STM32 PA9  TX  -> ESP32 GPIO16 RX
STM32 PA10 RX  <- ESP32 GPIO17 TX
STM32 GND      -- ESP32 GND
115200 8N1
```

The custom linker script reserves STM32F411 sector 7 for the trusted reference table.

## 6. Flash the new ESP32 firmware

```bash
cd ~/FIVSED_GUI/esp32
pio run
pio run -t upload
```

The ESP32 now sends a CRC-protected `ESP32_HEARTBEAT` frame every 5 seconds. STM32 receives it and returns an authenticated `ESP32_HEARTBEAT_ACK` containing `ACK: ESP32_ACTIVE`.

The UART handshake does not require Wi-Fi or a CA certificate. Wi-Fi/web upload does require the existing provisioned SSID, password, endpoint, API key, device ID, and CA certificate in ESP32 NVS.

## 7. Verify the handshake before scanning

Monitor the ESP32 USB serial console. You should see messages such as:

```text
ESP32_HEARTBEAT seq=1 send=OK
STM32_HEARTBEAT_ACK: ACK: ESP32_ACTIVE
COMPONENT_HEARTBEAT: STM32=ACTIVE PI=ACTIVE
```

On the Raspberry Pi FIVSED header, the steady state should become:

```text
PI: CONNECTED    STM32: CONNECTED    ESP32: CONNECTED
```

Do not add debugging `Serial.print()` strings to the STM32 PA9/PA10 UART because that link is the binary protocol. Debug output belongs on the ESP32 USB console or the Pi GUI log.

## 8. Verify Chip #3

With Chip #3 connected to Raspberry Pi SPI1 CE0 and STM32 connected over USB CDC, refresh the Targets page. v22 reads the synthetic `FIVSED-META` block at offset `0x1000`, so the detail area should show the provisioned Lenovo/ThinkPad fields instead of the generic `W25Q64 Target` label.

Then use the physical STM32 REGISTER action before the first provisioning scan. The trusted reference is stored in STM32 internal Flash; the GUI cannot directly replace it.
