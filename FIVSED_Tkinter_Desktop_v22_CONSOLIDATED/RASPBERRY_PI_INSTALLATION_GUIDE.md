# FIVSED Raspberry Pi Installation & Configuration Guide

This guide provides the complete, step-by-step terminal instructions to set up, configure, wire, and run the **FIVSED (Firmware Integrity Verification and Security Event Detection)** appliance on a **Raspberry Pi 3B+** (or Raspberry Pi 4) running **Raspberry Pi OS (Debian 12 Bookworm / Debian 11 Bullseye)**.

---

## 1. Hardware Architecture & Pinout Wiring

The Raspberry Pi serves as the **operator appliance and firmware acquisition engine**. It reads target flash memory over high-speed SPI and streams raw firmware images over native USB CDC to the STM32F411 security core.

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

### 1.1 Target W25Q64 SPI NOR Flash Wiring (Raspberry Pi SPI1 CE0)
> [!NOTE]
> FIVSED uses **SPI1** (`/dev/spidev1.0`) so that touchscreens using SPI0 can operate simultaneously without bus contention.

| W25Q64 Pin | Raspberry Pi 40-Pin Header | Pi GPIO / Function | Notes |
| :--- | :--- | :--- | :--- |
| **VCC** | **Pin 17** | **3.3V Power** | **NEVER** connect to 5V! |
| **GND** | **Pin 25** | **GND** | Common ground reference |
| **CS / CE** | **Pin 12** | **GPIO 18** | SPI1 Chip Select 0 (`SPI1_CE0_N`) |
| **DO / MISO**| **Pin 35** | **GPIO 19** | SPI1 Data Out / MISO (`SPI1_MISO`)|
| **DI / MOSI**| **Pin 38** | **GPIO 20** | SPI1 Data In / MOSI (`SPI1_MOSI`) |
| **CLK / SCLK**| **Pin 40** | **GPIO 21** | SPI1 Serial Clock (`SPI1_SCLK`) |

### 1.2 Physical Appliance Buttons
Three momentary pushbuttons provide clean physical control independent of the touch UI:

| Button Function | GPIO Pin | Physical Pin | Ground Pin | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Shutdown** | **GPIO 26** | Pin 37 | Pin 39 (GND) | Handled by kernel overlay `gpio-shutdown` |
| **Reboot** | **GPIO 13** | Pin 33 | Pin 34 (GND) | Handled by `fivsed-reboot-button.service` (hold 1.5s) |
| **Wake / Power-On** | **GPIO 3** | Pin 5 | Pin 6 (GND) | Hardware wake from halt / power down |

### 1.3 STM32 USB CDC Connection
Connect the STM32F411 USB Type-C port directly to any USB port on the Raspberry Pi with a high-quality data cable. It will enumerate automatically as `/dev/ttyACM0` (or `/dev/ttyACM1`).

---

## 2. Prerequisites & Initial OS Setup

Start with a fresh **Raspberry Pi OS Lite** or **Raspberry Pi OS Desktop** (64-bit or 32-bit recommended, Debian Bookworm or Bullseye).

Connect to the Raspberry Pi via SSH or local console as the default user (e.g., `pi` or `fivsed`):

```bash
# Update repository packages
sudo apt update && sudo apt upgrade -y

# Install git, curl, build essentials, and core system utilities
sudo apt install -y git curl wget build-essential python3-dev python3-pip python3-venv
```

---

## 3. Clone Repository & Directory Setup

Place the repository in the user's home directory:

```bash
cd ~
git clone https://github.com/vickyadityaraj/FIVSED_Hardware_Code.git
cd FIVSED_Hardware_Code/FIVSED_Tkinter_Desktop_v22_CONSOLIDATED
```

Verify that all shell scripts are executable:
```bash
chmod +x setup-tkinter-desktop.sh
chmod +x start-fivsed.sh
chmod +x rotate-display-left.sh
chmod +x fivsed-touch-correction.sh
chmod +x pi-appliance/install-reboot-button.sh
```

---

## 4. Run Desktop & Appliance Installation Script

The script `setup-tkinter-desktop.sh` configures the entire Linux environment:
1. Adds user to `dialout` and `spi` groups.
2. Installs X11, Openbox, LightDM, Tkinter, and Python runtime libraries.
3. Configures LightDM automatic graphical login into Openbox.
4. Enables the `spi1-1cs` device tree overlay in `/boot/firmware/config.txt` (or `/boot/config.txt`).
5. Configures the hardware `gpio-shutdown` button on GPIO 26.
6. Sets up Openbox autostart to automatically execute rotation, touch calibration, and the GUI on boot.

Run the script as your normal user (**DO NOT run with `sudo`**; the script uses `sudo` internally where needed):

```bash
./setup-tkinter-desktop.sh
```

---

## 5. Python Virtual Environment & Dependencies

Modern Raspberry Pi OS (Debian 12 Bookworm) uses PEP 668 managed environments. Create a dedicated virtual environment with system site packages enabled (so that hardware bindings like `python3-spidev` and `python3-tk` are seamlessly shared):

```bash
cd ~/FIVSED_Hardware_Code/FIVSED_Tkinter_Desktop_v22_CONSOLIDATED

# Create .venv with access to system packages
python3 -m venv --system-site-packages .venv

# Activate environment
source .venv/bin/activate

# Upgrade pip and install requirements
pip install --upgrade pip
pip install -r requirements.txt
```

Packages installed:
- `Flask>=3.0,<4`: Backend REST API and web endpoints.
- `pyserial>=3.5,<4`: Serial communication with STM32 USB CDC and ESP32.
- `psutil>=5.9,<7`: Raspberry Pi CPU, memory, and temperature metrics.
- `esptool>=5,<6`: ESP32 target flash acquisition.
- `spidev>=3.6`: Hardware SPI driver for Winbond W25Q64.
- `gpiozero>=2.0,<3`: GPIO button monitoring.

---

## 6. Install the Physical Hardware Reboot Button Service

Install the systemd background daemon that monitors GPIO 13 for physical reboot button presses:

```bash
cd ~/FIVSED_Hardware_Code/FIVSED_Tkinter_Desktop_v22_CONSOLIDATED
./pi-appliance/install-reboot-button.sh
```

Check the status of the service:
```bash
sudo systemctl status fivsed-reboot-button.service
```

---

## 7. Reboot the Raspberry Pi

To apply the SPI1 device tree overlay, group memberships, and Openbox display configuration, reboot the system:

```bash
sudo reboot
```

After rebooting:
1. The Pi automatically logs into the Openbox session.
2. `rotate-display-left.sh` rotates the HDMI display 90 degrees LEFT into 480x800 portrait mode.
3. `fivsed-touch-correction.sh` applies the coordinate transformation matrix to align touchscreen input.
4. `start-fivsed.sh` launches the FIVSED Tkinter GUI in full-screen portrait orientation.

---

## 8. Manual Execution & CLI Commands

### 8.1 Launching the GUI Manually (from Local X11 Terminal or Desktop)
If you close the application or are running from a local terminal:
```bash
cd ~/FIVSED_Hardware_Code/FIVSED_Tkinter_Desktop_v22_CONSOLIDATED
./start-fivsed.sh
```
Or with custom display environment:
```bash
DISPLAY=:0 ./start-fivsed.sh
```

### 8.2 Launching the Backend REST API Server
If you want to run the optional Flask REST API alongside or for headless testing:
```bash
cd ~/FIVSED_Hardware_Code/FIVSED_Tkinter_Desktop_v22_CONSOLIDATED
source .venv/bin/activate
python3 -m backend.main
```
The API will be available at `http://127.0.0.1:8765/api/status`.

### 8.3 Running Unit Tests
Validate the protocol engine and metadata parser:
```bash
cd ~/FIVSED_Hardware_Code/FIVSED_Tkinter_Desktop_v22_CONSOLIDATED
source .venv/bin/activate
python3 -m unittest discover tests
```

---

## 9. Verification & Troubleshooting Commands

### 9.1 Check SPI1 Device Presence
Ensure the W25Q64 SPI device node is created:
```bash
ls -l /dev/spidev1.0
```
Expected output:
```text
crw-rw---- 1 root spi 153, 0 ... /dev/spidev1.0
```

### 9.2 Check STM32 USB CDC Enumeration
Plug the STM32F411 board into the Pi USB and inspect kernel messages:
```bash
dmesg | grep -i "cdc_acm"
ls -l /dev/ttyACM*
```
Expected output:
```text
cdc_acm 1-1.3:1.0: ttyACM0: USB ACM device
crw-rw---- 1 root dialout 166, 0 ... /dev/ttyACM0
```

### 9.3 Inspect Application Logs
If the display or GUI does not start, inspect the autostart logs in the user's home directory:
```bash
cat ~/.fivsed-rotation.log
cat ~/.fivsed-touch-correction.log
cat ~/.fivsed-gui.log
```

### 9.4 Test Display Rotation Manually
```bash
DISPLAY=:0 xrandr --query
DISPLAY=:0 ./rotate-display-left.sh
```

### 9.5 Test Touch Calibration Manually
```bash
DISPLAY=:0 xinput list
DISPLAY=:0 ./fivsed-touch-correction.sh
```
