#!/usr/bin/env python3
"""SPIKE diagnostics: count evdev events per passthrough device (host-side).

Run while the Moonlight client produces input; prints per-device event
counts (type/code) after N seconds. Locates the virtual devices (Sunshine's
"* passthrough" + the keeper) via /proc/bus/input/devices.
"""
import os
import select
import struct
import sys
import time

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 20

devs = {}
name = None
for line in open("/proc/bus/input/devices"):
    if line.startswith("N: Name="):
        name = line.split("=", 1)[1].strip().strip('"')
    elif line.startswith("H: Handlers=") and name and (
            "passthrough" in name or "Sunshine" in name):
        for tok in line.split():
            if tok.startswith("event"):
                devs[f"/dev/input/{tok}"] = name

fds = {}
for path, n in devs.items():
    try:
        fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = (path, n)
    except OSError as e:
        print(f"skip {path} ({n}): {e}")

counts = {}
first = {}
end = time.time() + DUR
EV_SIZE = struct.calcsize("llHHi")
while time.time() < end:
    r, _, _ = select.select(list(fds), [], [], 0.5)
    for fd in r:
        try:
            data = os.read(fd, EV_SIZE * 64)
        except OSError:
            continue
        for off in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
            _, _, etype, code, value = struct.unpack_from("llHHi", data, off)
            if etype == 0:
                continue  # SYN
            key = (fds[fd][1], etype, code)
            counts[key] = counts.get(key, 0) + 1
            first.setdefault(key, value)

for (n, etype, code), c in sorted(counts.items(), key=lambda kv: -kv[1]):
    print(f"{c:6}  {n:35} type={etype} code={code} first={first[(n, etype, code)]}")
if not counts:
    print("NO EVENTS on any passthrough device")
