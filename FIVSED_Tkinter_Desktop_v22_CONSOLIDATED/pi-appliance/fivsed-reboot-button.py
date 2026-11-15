#!/home/fivsed/FIVSED_GUI/.venv/bin/python
from gpiozero import Button
import signal
import subprocess

button = Button(13, pull_up=True, bounce_time=0.3)

# Do not reboot immediately if the button is held while Linux is booting.
button.wait_for_release()


def reboot() -> None:
    subprocess.run(["/usr/bin/systemctl", "reboot"], check=False)


button.when_pressed = reboot
signal.pause()
