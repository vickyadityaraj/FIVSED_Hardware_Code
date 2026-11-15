# STM32 Configuration, CubeMX Setup, CubeIDE Build & Programming Guide

This document provides complete instructions for configuring, building, and flashing the **STM32F411CEU6 ("Black Pill")** microcontroller, which acts as the **Sole Root of Security Authority** in the **FIVSED (Firmware Integrity Verification and Security Event Detection)** system.

---

## 1. System Role & Security Boundary

In the FIVSED architecture:
- **STM32F411CEU6** is the **sole integrity authority**.
- It receives raw firmware bytes over native **USB CDC** from the Raspberry Pi.
- It computes the **SHA-256** digest incrementally in hardware/firmware.
- It compares the calculated hash against trusted references stored securely in its internal flash memory (**Sector 7, address `0x08060000`**).
- It transmits HMAC-authenticated verification decisions and status heartbeats over **USART1** to the ESP32 gateway.
- It enforces **physical push-button authorization** for registering, rebaselining, revoking, or restoring target firmware references. Neither the Raspberry Pi GUI nor the web interface can overwrite trusted references without local physical confirmation.

---

## 2. Complete Port & Pin Mapping (CubeMX Ports)

The following table details every port, pin, peripheral mode, and electrical configuration used on the STM32F411CEU6:

| Port / Pin | Peripheral Signal | CubeMX Mode | Electrical Config | Connected To / Function |
| :--- | :--- | :--- | :--- | :--- |
| **PA9** | `USART1_TX` | Asynchronous | Alternate Function PP | **ESP32 GPIO 16 (RX)** — 115200 8N1 |
| **PA10** | `USART1_RX` | Asynchronous | Alternate Function PP | **ESP32 GPIO 17 (TX)** — 115200 8N1 |
| **PA11** | `USB_OTG_FS_DM` | Device_Only | Alternate Function | **Raspberry Pi USB (Data - / White)** |
| **PA12** | `USB_OTG_FS_DP` | Device_Only | Alternate Function | **Raspberry Pi USB (Data + / Green)** |
| **PA13** | `SYS_JTMS-SWDIO` | Serial Wire | Alternate Function | **ST-Link V2 SWDIO** (Pin 2) |
| **PA14** | `SYS_JTCK-SWCLK` | Serial Wire | Alternate Function | **ST-Link V2 SWCLK** (Pin 4) |
| **PH0** | `RCC_OSC_IN` | HSE Oscillator | High Speed External | **25 MHz External Crystal** |
| **PH1** | `RCC_OSC_OUT` | HSE Oscillator | High Speed External | **25 MHz External Crystal** |
| **PA0** | `GPIO_Input` | Input Pull-up | Active-Low to GND | **Register Pushbutton** (`REGISTER_PIN`) |
| **PA1** | `GPIO_Input` | Input Pull-up | Active-Low to GND | **Restore Pushbutton** (`RESTORE_PIN`) |
| **PB4** | `GPIO_Input` | Input Pull-up | Active-Low to GND | **Rebaseline Pushbutton** (`REBASELINE_PIN`) |
| **PB5** | `GPIO_Input` | Input Pull-up | Active-Low to GND | **Revoke Pushbutton** (`REVOKE_PIN`) |
| **PC13** | `GPIO_Output` | Output Push-Pull | Active-Low LED | **Black Pill On-board LED** (`ONBOARD_LED_PIN`) |
| **PC14** | `GPIO_Output` | Output Push-Pull | Active-High Output | **Security / Tamper Alert Output** (`ALERT_PIN`) |
| **GND** | `GND` | Ground | 0V Reference | Common GND with Pi, ESP32, and ST-Link |
| **3.3V** | `VDD` | Power Input | 3.3V DC | Powered from USB or ST-Link |

---

## 3. STM32CubeMX Configuration Step-by-Step

The project includes the pre-configured CubeMX file:
[`STM32/fivsed_v2/fivsed_v2.ioc`](file:///d:/FIVSED_Hardware_Code/FIVSED_Tkinter_Desktop_v22_CONSOLIDATED/STM32/fivsed_v2/fivsed_v2.ioc).

If recreating or modifying the configuration in **STM32CubeMX** (v6.12 or newer):

### 3.1 MCU Selection
1. Open STM32CubeMX and click **New Project**.
2. In the MCU Selector, search for: `STM32F411CEU6`.
3. Select the `UFQFPN48` package and click **Start Project**.

### 3.2 System Core Setup
1. **RCC (Reset and Clock Control)**:
   - **High Speed Clock (HSE)**: Select `Crystal/Ceramic Resonator` (25 MHz crystal on Black Pill).
   - **Low Speed Clock (LSE)**: `Disable`.
2. **SYS**:
   - **Debug**: Select `Serial Wire` (configures PA13 as SWDIO, PA14 as SWCLK).
   - **Timebase Source**: Select `SysTick`.

### 3.3 Connectivity Setup
1. **USART1** (Communication with ESP32):
   - **Mode**: Select `Asynchronous`.
   - Under **Configuration -> Parameter Settings**:
     - **Baud Rate**: `115200 Bits/s`.
     - **Word Length**: `8 Bits`.
     - **Parity**: `None`.
     - **Stop Bits**: `1`.
     - **Hardware Flow Control**: `Disable`.
   - Under **NVIC Settings**:
     - Check **USART1 global interrupt** -> **Enabled** (Priority: 0).
   - Verify Pins: **PA9** = `USART1_TX`, **PA10** = `USART1_RX`.

2. **USB_OTG_FS** (Communication with Raspberry Pi):
   - **Mode**: Select `Device_Only`.
   - Under **NVIC Settings**:
     - Check **USB On The Go FS global interrupt** -> **Enabled** (Priority: 0).
   - Verify Pins: **PA11** = `USB_OTG_FS_DM`, **PA12** = `USB_OTG_FS_DP`.

### 3.4 Middleware Setup
1. **USB_DEVICE**:
   - Under **Mode**:
     - Select **Class For FS IP**: `Communication Device Class (CDC) / Virtual Port Com`.
   - Under **Parameter Settings**:
     - Keep default USB descriptors (PID: `0x5740`, VID: `0x0483` STMicroelectronics).

### 3.5 GPIO Ports Setup
Configure the physical buttons and indicators in the **Pinout View**:
1. Click on **PA0** -> Select `GPIO_Input`.
   - In System Core -> GPIO -> PA0: GPIO Mode = `Input`, GPIO Pull-up/Pull-down = `Pull-up`, User Label = `REGISTER_PIN`.
2. Click on **PA1** -> Select `GPIO_Input`.
   - GPIO Mode = `Input`, GPIO Pull-up/Pull-down = `Pull-up`, User Label = `RESTORE_PIN`.
3. Click on **PB4** -> Select `GPIO_Input`.
   - GPIO Mode = `Input`, GPIO Pull-up/Pull-down = `Pull-up`, User Label = `REBASELINE_PIN`.
4. Click on **PB5** -> Select `GPIO_Input`.
   - GPIO Mode = `Input`, GPIO Pull-up/Pull-down = `Pull-up`, User Label = `REVOKE_PIN`.
5. Click on **PC13** -> Select `GPIO_Output`.
   - GPIO Mode = `Output Push-Pull`, Pull = `No pull`, Speed = `Low`, Initial output level = `High` (LED OFF), User Label = `ONBOARD_LED_PIN`.
6. Click on **PC14** -> Select `GPIO_Output`.
   - GPIO Mode = `Output Push-Pull`, Pull = `No pull`, Speed = `Low`, Initial output level = `Low` (Alarm OFF), User Label = `ALERT_PIN`.

### 3.6 Clock Tree Configuration
Navigate to the **Clock Configuration** tab:
1. Input Frequency (**HSE**): Set to `25` MHz.
2. Select **PLL Source Mux**: `HSE`.
3. Set **PLLM** to `/ 25`.
4. Set **PLLN** (multiplier) to `* 192`.
5. Set **PLLP** (System Clock divider) to `/ 2`.
6. Select **System Clock Mux (SYSCLK)**: `PLLCLK`.
7. **SYSCLK** will now equal **96 MHz** (maximum rated stable frequency for STM32F411).
8. Set **AHB Prescaler**: `/ 1` (HCLK = 96 MHz).
9. Set **APB1 Prescaler**: `/ 2` (APB1 peripheral clock = 48 MHz).
10. Set **APB2 Prescaler**: `/ 1` (APB2 clock = 96 MHz).
11. Set **PLLQ** (USB OTG divider) to `/ 4` -> **48 MHz** (Exact 48 MHz required for USB OTG FS!).

### 3.7 Project Manager Settings
1. Go to **Project Manager** tab:
   - **Project Name**: `fivsed_v2`
   - **Project Location**: `.../FIVSED_Tkinter_Desktop_v22_CONSOLIDATED/STM32`
   - **Toolchain / IDE**: Select `STM32CubeIDE`.
   - **Generate Under Root**: Checked.
2. Go to **Code Generator** sub-tab:
   - Check **Copy only the necessary library files**.
   - Check **Keep User Code when re-generating** (Crucial to preserve custom code!).
3. Click **GENERATE CODE** (Top-right button).

---

## 4. STM32CubeIDE Build Steps

### 4.1 Importing the Project into STM32CubeIDE
1. Launch **STM32CubeIDE**.
2. Select or create an active workspace directory.
3. Click **File -> Import...** from the top menu.
4. Expand **General**, select **Existing Projects into Workspace**, and click **Next**.
5. Click **Browse...** next to *Select root directory* and select:
   `D:\FIVSED_Hardware_Code\FIVSED_Tkinter_Desktop_v22_CONSOLIDATED\STM32\fivsed_v2`
6. Ensure `fivsed_v2` is checked in the Projects list.
7. Uncheck *Copy projects into workspace* (so you work directly within the repository).
8. Click **Finish**.

### 4.2 Project Architecture in IDE
The imported project consists of:
- `Core/Src/main.c`: Contains the FIVSED safety core, SHA-256 computation engine, binary packet parser for the Pi USB frame (`0xF5`), UART protocol handler for ESP32 (`0x5A` / `0xA5`), button polling routines, and Sector 7 Flash storage management (`0x08060000`).
- `USB_DEVICE/App/usbd_cdc_if.c`: CDC Receive callback (`CDC_Receive_FS`) which pipes incoming USB stream chunks directly into `FIVSED_USB_RxFeed()`.
- `Drivers/STM32F4xx_HAL_Driver/`: ST HAL drivers for GPIO, UART, Flash, RCC, and USB.
- `Middlewares/ST/STM32_USB_Device_Library/`: ST CDC device stack.
- `STM32F411CEUX_FLASH.ld`: Linker script setting RAM (128 KB) and Flash (512 KB).

### 4.3 Building the Firmware
1. In the Project Explorer, right-click `fivsed_v2` -> **Clean Project**.
2. Right-click `fivsed_v2` -> **Build Project** (or press `Ctrl+B`).
3. The build console should output:
   ```text
   Finished building target: fivsed_v2.elf
   arm-none-eabi-size fivsed_v2.elf
      text    data     bss     dec     hex filename
     32480     388    6824   39692    9acc fivsed_v2.elf
   Build Finished. 0 errors, 0 warnings.
   ```
4. Output files are generated in `Debug/`:
   - `fivsed_v2.elf`: Executable and Linkable Format for debugging.
   - `fivsed_v2.bin` / `fivsed_v2.hex`: Flash binary images.

---

## 5. STM32 Programming & Flashing Steps

### 5.1 Flashing Method 1: STM32CubeIDE with ST-Link V2 (Recommended)

#### Wiring ST-Link V2 to STM32 Black Pill:
| ST-Link V2 Pin | STM32 Black Pill Pin |
| :--- | :--- |
| **Pin 1 (3.3V)** | **3.3V** *(Skip if board is powered via USB!)* |
| **Pin 2 (SWDIO)** | **PA13 (SWDIO)** |
| **Pin 4 (SWCLK)** | **PA14 (SWCLK)** |
| **Pin 6 (GND)** | **GND** |

> [!CAUTION]
> If the STM32 board is plugged into the Raspberry Pi via USB, **do NOT connect the 3.3V pin** from the ST-Link to avoid dual-power conflicts. Connect only SWDIO, SWCLK, and GND.

#### Flashing via IDE:
1. Connect the ST-Link V2 to your computer's USB port.
2. In STM32CubeIDE, click **Run -> Run Configurations...**.
3. Under **STM32 C/C++ Application**, double-click `fivsed_v2 Debug`.
4. In the **Debugger** tab:
   - Debug probe: `ST-LINK (ST-LINK GDB server)`.
   - Interface: `SWD`.
   - Reset Mode: `Software system reset`.
5. Click **Apply**, then **Run**.
6. The IDE compiles and flashes the binary directly to address `0x08000000` and resets the MCU.

---

### 5.2 Flashing Method 2: STM32CubeProgrammer (GUI or CLI)

If you prefer using the standalone **STM32CubeProgrammer** utility:

#### Using GUI:
1. Open **STM32CubeProgrammer**.
2. Select **ST-LINK** in the top-right connection dropdown.
3. Click **Connect**.
4. Click the **Open file** tab and select `Debug/fivsed_v2.elf` or `Debug/fivsed_v2.bin`.
5. If using `.bin`, set Start Address to `0x08000000`.
6. Click **Download** / **Program**.
7. Click **Disconnect**.

#### Using Command-Line Interface (CLI):
```bash
STM32_Programmer_CLI -c port=SWD freq=4000 -w "Debug/fivsed_v2.elf" -v -rst
```

---

### 5.3 Flashing Method 3: USB DFU Mode (Without ST-Link Hardware!)

The STM32F411 has a built-in ROM bootloader that supports **DFU (Device Firmware Upgrade)** over USB.

#### Entering DFU Mode:
1. Connect the Black Pill to your computer/Pi via USB.
2. Press and **HOLD** the `BOOT0` button.
3. While holding `BOOT0`, press and release the `NRST` (Reset) button.
4. Release the `BOOT0` button.
5. The MCU is now in DFU Bootloader mode.

#### Flashing via `dfu-util` (Linux / Raspberry Pi / macOS / Windows):
Check if device is detected:
```bash
dfu-util -l
```
Expected output:
```text
Found DFU: [0483:df11] ver=2200, devnum=..., cfg=1, intf=0, alt=0, name="@Internal Flash  /0x08000000/04*016Kg,01*064Kg,03*128Kg"
```

Flash the compiled binary:
```bash
# Convert elf to bin if needed:
arm-none-eabi-objcopy -O binary Debug/fivsed_v2.elf Debug/fivsed_v2.bin

# Flash binary via DFU to address 0x08000000 and restart:
dfu-util -a 0 -s 0x08000000:leave -D Debug/fivsed_v2.bin
```

---

### 5.4 Flashing Method 4: Alternative PlatformIO Build

If you are using the alternative PlatformIO configuration provided in [`stm32 as per chatgpt`](file:///d:/FIVSED_Hardware_Code/FIVSED_Tkinter_Desktop_v22_CONSOLIDATED/stm32%20as%20per%20chatgpt):

```bash
cd "D:\FIVSED_Hardware_Code\FIVSED_Tkinter_Desktop_v22_CONSOLIDATED\stm32 as per chatgpt"
pio run
pio run -t upload
```

---

## 6. Post-Flash Verification & Operation

Once flashed and powered up:

1. **LED Indicators**:
   - The on-board LED on **PC13** will illuminate and blink during USB stream processing.
   - The **PC14 Alert output** remains `LOW` during normal operation and goes `HIGH` if a firmware hash mismatch or tampering condition is detected.

2. **USB Enumeration on Raspberry Pi**:
   Connect the STM32 USB port to the Raspberry Pi. Run on the Pi terminal:
   ```bash
   dmesg | tail -n 20
   ```
   You should see:
   ```text
   usb 1-1.3: new full-speed USB device number ... using dwc_otg
   cdc_acm 1-1.3:1.0: ttyACM0: USB ACM device
   ```

3. **Physical Buttons Operation**:
   - **PA0 (REGISTER)**: Press and hold (>800ms) to arm the STM32 for registering the attached target's current firmware as the trusted reference.
   - **PB4 (REBASELINE)**: Press and hold (>800ms) to update an existing registered reference.
   - **PB5 (REVOKE)**: Press and hold (>800ms) to revoke authorization for the active target slot.
   - **PA1 (RESTORE)**: Press and hold (>800ms) to clear all references and reset Sector 7 Flash to factory defaults.
