"""Finds the cameras that are connected and decides which one is the front and which the side camera.

Priority: the Raspberry Pi (AI) Camera is the front camera. A USB webcam becomes the side camera when
the Pi camera is there, and the front camera when it is not. At least one camera is needed."""

import glob
import os
import re
import shutil
import subprocess
import sys


def parse_rpicam_list(text):
    """True if `rpicam-hello --list-cameras` lists at least one camera."""
    if "No cameras available" in text:
        return False
    return bool(re.search(r"^\s*\d+\s*:\s*\S+", text, re.M))


def parse_v4l2_devices(text):
    """Indexes of USB cameras from `v4l2-ctl --list-devices` (first /dev/videoN of each USB device)."""
    found, usb_block = [], False
    for line in text.splitlines():
        if line and not line[0].isspace():
            usb_block = "usb" in line.lower()
            first = True
            continue
        m = re.match(r"\s*/dev/video(\d+)", line)
        if m and usb_block and first:
            found.append(int(m.group(1)))
            first = False
    return found


def detect_picam(timeout=8):
    exe = shutil.which("rpicam-hello") or shutil.which("libcamera-hello")
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "--list-cameras"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return parse_rpicam_list(out.stdout + out.stderr)


def detect_usb_cameras(probe_max=4):
    """USB webcam indexes. Linux: read /sys (no extra tools needed); otherwise try opening 0..probe_max."""
    if sys.platform.startswith("linux") and os.path.isdir("/sys/class/video4linux"):
        found = []
        for node in sorted(glob.glob("/sys/class/video4linux/video*"), key=lambda p: int(re.sub(r"\D", "", p) or 0)):
            dev = os.path.realpath(os.path.join(node, "device"))
            try:
                with open(os.path.join(node, "index")) as f:
                    first_node = f.read().strip() == "0"     # a webcam has 2 nodes; the first one gives video
            except OSError:
                first_node = True
            if "/usb" in dev and first_node:
                found.append(int(re.sub(r"\D", "", os.path.basename(node))))
        return found
    import cv2                                             # Windows / macOS laptop: just try them
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)   # no warnings for missing indexes
    except AttributeError:
        pass
    found = []
    for i in range(probe_max + 1):
        cap = cv2.VideoCapture(i)
        ok = cap.isOpened() and cap.read()[0]
        cap.release()
        if ok:
            found.append(i)
    return found


def choose(picam, usb):
    """-> (front, side). front is 'picam' or a webcam index, side is a webcam index or None."""
    if picam:
        return "picam", (usb[0] if usb else None)
    if usb:
        return usb[0], (usb[1] if len(usb) > 1 else None)
    return None, None


def detect():
    picam = detect_picam()
    usb = detect_usb_cameras()
    front, side = choose(picam, usb)
    print(f"[CAMERAS] Pi camera: {'yes' if picam else 'no'} | USB webcams: {usb or 'none'} "
          f"-> front: {front if front is not None else '-'}, side: {side if side is not None else 'none'}")
    return front, side
