#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

if [ "$(uname -s)" != "Linux" ]; then
  echo "This setup script is for Raspberry Pi OS/Linux only."
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this script as the normal FIVSED user, not with sudo."
  exit 1
fi

USER_NAME=$(id -un)
USER_HOME=${HOME}

# Native STM32 USB CDC appears as /dev/ttyACM*. Allow the FIVSED user to open it.
sudo usermod -aG dialout "${USER_NAME}" || true
sudo usermod -aG spi "${USER_NAME}" || true

printf '%s\n' "Installing the lightweight X11/Openbox desktop needed by Tkinter..."
sudo apt update
sudo apt install -y --no-install-recommends \
  xserver-xorg \
  xinit \
  openbox \
  lightdm \
  lightdm-gtk-greeter \
  x11-xserver-utils \
  xinput \
  python3-tk \
  python3-flask \
  python3-serial \
  python3-psutil \
  python3-spidev

sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-fivsed.conf >/dev/null <<CFG
[Seat:*]
autologin-user=${USER_NAME}
autologin-user-timeout=0
autologin-session=openbox
user-session=openbox
CFG

# FIVSED runs under Xorg + Openbox. Apply the 90-degree LEFT rotation after Xorg
# has started, because xrandr controls the X11/KMS output. Remove any older
# config.txt rotation directives so the screen is not rotated twice.
BOOT_CONFIG="/boot/firmware/config.txt"
if [ ! -f "$BOOT_CONFIG" ] && [ -f "/boot/config.txt" ]; then
  BOOT_CONFIG="/boot/config.txt"
fi

# Enable Raspberry Pi SPI1 for the default W25Q64 target path.
# SPI1 avoids SPI0 pins used by the touchscreen touch controller.
if [ -f "$BOOT_CONFIG" ]; then
  if ! grep -q "^dtoverlay=spi1-1cs$" "$BOOT_CONFIG"; then
    echo "Enabling SPI1 CE0 in $BOOT_CONFIG"
    printf '\ndtoverlay=spi1-1cs\n' | sudo tee -a "$BOOT_CONFIG" >/dev/null
  fi
  # Preserve the working physical shutdown button:
  # GPIO26 (pin 37) -> button -> GND (pin 39), active-low with pull-up.
  if ! grep -q "^dtoverlay=gpio-shutdown,gpio_pin=26" "$BOOT_CONFIG"; then
    echo "Enabling FIVSED GPIO26 shutdown button in $BOOT_CONFIG"
    printf '\ndtoverlay=gpio-shutdown,gpio_pin=26,active_low=1,gpio_pull=up,debounce=500\n' | sudo tee -a "$BOOT_CONFIG" >/dev/null
  fi
  echo "Removing older firmware rotation directives from $BOOT_CONFIG"
  sudo cp -a "$BOOT_CONFIG" "${BOOT_CONFIG}.fivsed-backup"
  sudo sed -i '/^[[:space:]]*display_hdmi_rotate=/d;/^[[:space:]]*display_rotate=/d;/^[[:space:]]*display_lcd_rotate=/d' "$BOOT_CONFIG"
fi

mkdir -p "${USER_HOME}/.config/openbox"
cat > "${USER_HOME}/.config/openbox/autostart" <<AUTOSTART
# FIVSED portrait appliance display
# Rotate X11 first, then start Tkinter.
"${ROOT_DIR}/rotate-display-left.sh" >>"${USER_HOME}/.fivsed-rotation-autostart.log" 2>&1
"${ROOT_DIR}/fivsed-touch-correction.sh" >>"${USER_HOME}/.fivsed-touch-autostart.log" 2>&1
"${ROOT_DIR}/start-fivsed.sh" >>"${USER_HOME}/.fivsed-gui.log" 2>&1 &
AUTOSTART

chmod +x "${ROOT_DIR}/start-fivsed.sh"
chmod +x "${ROOT_DIR}/setup-tkinter-desktop.sh"
chmod +x "${ROOT_DIR}/rotate-display-left.sh"
chmod +x "${ROOT_DIR}/fivsed-touch-correction.sh"

# Ensure the Openbox session launches the copy of FIVSED from this project directory.
# Re-running this script safely refreshes the autostart entry if the project directory changes.


sudo systemctl enable lightdm
sudo systemctl set-default graphical.target

cat <<MSG

FIVSED Tkinter desktop setup is complete.

The Pi will use:
  Xorg       -> graphical display
  Openbox    -> lightweight window manager
  LightDM    -> automatic graphical login
  Tkinter    -> native FIVSED application

No browser is used by the FIVSED desktop application.

Reboot the Raspberry Pi:
  sudo reboot

After reboot, the X desktop is rotated LEFT by 90° and the FIVSED Tkinter window starts in 480x800 portrait mode on the attached HDMI/touchscreen display.

For SSH/headless testing, do not expect the GUI window to appear in the SSH terminal. The GUI is displayed on the Pi's local graphical session.
MSG
