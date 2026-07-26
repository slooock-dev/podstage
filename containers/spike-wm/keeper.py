#!/usr/bin/env python3
"""Persistent dummy pointer ("keeper"): keeps the compositor's seat POINTER
capability alive across Sunshine's device churn, so gamescope's input-thread
wl_pointer is never released (the release/recreate cycle loses wl_pointer.enter
forever -> dead mouse in nested gamescope under labwc). Sends no events."""
import fcntl
import os
import signal
import struct
import time

UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566

fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
fcntl.ioctl(fd, UI_SET_EVBIT, 1)          # EV_KEY
fcntl.ioctl(fd, UI_SET_KEYBIT, 0x110)     # BTN_LEFT
fcntl.ioctl(fd, UI_SET_EVBIT, 2)          # EV_REL
fcntl.ioctl(fd, UI_SET_RELBIT, 0)         # REL_X
fcntl.ioctl(fd, UI_SET_RELBIT, 1)         # REL_Y
dev = struct.pack("80sHHHHi", b"podstage passthrough keeper", 3, 0x1234, 0x5678, 1, 0) + b"\0" * 1024
os.write(fd, dev)
fcntl.ioctl(fd, UI_DEV_CREATE)
print("keeper up", flush=True)

running = True
def stop(*_):
    global running
    running = False
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
while running:
    time.sleep(5)
fcntl.ioctl(fd, UI_DEV_DESTROY)
os.close(fd)
