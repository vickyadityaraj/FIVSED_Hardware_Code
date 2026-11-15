# FIVSED Raspberry Pi appliance configuration

These files reproduce the Raspberry Pi hardware/UI integrations that are outside the Python application package.

## Display

- HDMI panel: 800x480 physical panel presented as 480x800 portrait.
- `../rotate-display-left.sh` applies `xrandr --output <connected> --rotate left` after Xorg starts.
- `../fivsed-touch-correction.sh` applies the working XInput coordinate matrix:
  `1 0 0 0 -1 1 0 0 1`
- Openbox autostart runs rotation, touch correction, and then the Tkinter application.

## Physical buttons

- Shutdown: GPIO26 / physical pin 37 -> momentary button -> GND pin 39.
  Raspberry Pi OS configuration uses:
  `dtoverlay=gpio-shutdown,gpio_pin=26,active_low=1,gpio_pull=up,debounce=500`
- Wake/power-up: GPIO3 / physical pin 5 -> momentary button -> GND pin 6.
  This is the normal Raspberry Pi low-power wake path.
- Reboot: GPIO13 / physical pin 33 -> momentary button -> GND pin 34.
  Install `fivsed-reboot-button.service` as a systemd service.

## Important

The shutdown/wake/reboot functions are OS/hardware integration, not FIVSED security decisions. They must remain independent of the STM32 reference table.
