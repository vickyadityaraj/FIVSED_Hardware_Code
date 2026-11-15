FIVSED v22 display and touch configuration
===========================================

The Raspberry Pi appliance uses the attached HDMI panel as a 480x800 portrait surface.

Display rotation
-----------------
After Xorg starts, `rotate-display-left.sh` detects the connected X11 output and runs:

    xrandr --output <connected-output> --rotate left

The project intentionally removes older `display_hdmi_rotate`, `display_rotate`, and
`display_lcd_rotate` directives from Raspberry Pi firmware configuration to avoid double
rotation/blank-display problems.

Touch correction
----------------
After the display is rotated, `fivsed-touch-correction.sh` identifies the XPT2046/
touchscreen input device and applies:

    1 0 0
    0 -1 1
    0 0 1

This corrects the working inverted-Y touch response used by the FIVSED portrait display.

Openbox startup order
---------------------
1. Rotate the X11 output LEFT by 90 degrees.
2. Apply the touch coordinate transformation.
3. Start the native Tkinter FIVSED desktop application.

No browser is required for the local operator GUI.
