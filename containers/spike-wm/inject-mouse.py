#!/usr/bin/env python3
"""Host-side virtual mouse for pointer-path testing without a Moonlight client.

Creates a uinput mouse named '*passthrough*' (the udev rule pins it to seat9
and chowns it to the user; the seat shim's inotify fake-udev hands it to the
compositor in the container), then sends deliberate motion (net > 3 px) and a
left click, which also satisfies the cage activation gate.
"""
import fcntl
import os
import struct
import time

UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
REL_X, REL_Y = 0x00, 0x01
BTN_LEFT = 0x110

fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_LEFT)
fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
fcntl.ioctl(fd, UI_SET_RELBIT, REL_X)
fcntl.ioctl(fd, UI_SET_RELBIT, REL_Y)

# struct uinput_user_dev: name[80], id(bustype,vendor,product,version), ff, abs arrays
dev = struct.pack("80sHHHHi", b"podstage passthrough mouse", 0x03, 0x1234, 0x5678, 1, 0)
dev += b"\0" * 1024
os.write(fd, dev)
fcntl.ioctl(fd, UI_DEV_CREATE)
time.sleep(2.5)  # udev rule + inotify shim + libinput attach

def emit(etype, code, value):
    os.write(fd, struct.pack("llHHi", 0, 0, etype, code, value))
    os.write(fd, struct.pack("llHHi", 0, 0, EV_SYN, 0, 0))

# Deliberate motion: net 200 px left-up in steps, then a click, more motion.
for _ in range(20):
    emit(EV_REL, REL_X, -10)
    emit(EV_REL, REL_Y, -10)
    time.sleep(0.03)
emit(EV_KEY, BTN_LEFT, 1)
time.sleep(0.1)
emit(EV_KEY, BTN_LEFT, 0)
for _ in range(10):
    emit(EV_REL, REL_X, -8)
    time.sleep(0.03)
time.sleep(1)
fcntl.ioctl(fd, UI_DEV_DESTROY)
os.close(fd)
print("injected: 200px motion + click + 80px motion")
