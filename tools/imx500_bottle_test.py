"""Feasibility test: can the Raspberry Pi AI Camera's built-in object detector (IMX500, SSD MobileNetV2 trained
on COCO) see a bottle held in the hand? The network runs on the camera chip itself, so the Pi's CPU is free.
Runs with the SYSTEM Python (Picamera2 is installed there, not in fitform_env), with the FitForm app stopped:
  /usr/bin/python3 tools/imx500_bottle_test.py            # 60 s, preview on the Pi screen, log in the terminal
  /usr/bin/python3 tools/imx500_bottle_test.py 90 0.3     # seconds, score threshold
Every 0.5 s it prints what was detected (label, score, box); at the end a summary of how often a bottle was seen."""

import json
import sys
import time

import numpy as np
from libcamera import Transform
from picamera2 import Picamera2
from picamera2.devices import IMX500

MODEL = "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk"
LABELS = json.load(open("/usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json"))["imx500_object_detection"]["classes"]
WATCH = {"bottle", "cup", "wine glass", "sports ball", "cell phone", "remote", "baseball bat"}   # hand-held things


def box_overlay(shape, dets):
    """RGBA overlay with a rectangle per detection (Picamera2 draws it over the preview)."""
    h, w = shape
    ov = np.zeros((h, w, 4), np.uint8)
    for label, score, (x, y, bw, bh) in dets:
        col = (0, 255, 0, 255) if label == "bottle" else (255, 160, 0, 200)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(w - 1, x + bw), min(h - 1, y + bh)
        for t in range(3):
            ov[y0 + t, x0:x1] = col
            ov[y1 - t, x0:x1] = col
            ov[y0:y1, x0 + t] = col
            ov[y0:y1, x1 - t] = col
    return ov


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    imx500 = IMX500(MODEL)
    picam2 = Picamera2(imx500.camera_num)
    # the camera is mounted upside down: flip the sensor read-out (the network then sees an upright picture too)
    config = picam2.create_preview_configuration(main={"size": (640, 480)}, controls={"FrameRate": 30},
                                                 transform=Transform(hflip=1, vflip=1), buffer_count=12)
    print("Loading the network onto the camera (first time can take a minute)...")
    imx500.show_network_fw_progress_bar()
    picam2.start(config, show_preview=True)
    frames = with_bottle = 0
    best = 0.0
    last_print = 0.0
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            md = picam2.capture_metadata()
            out = imx500.get_outputs(md, add_batch=True)
            if out is None:
                continue
            frames += 1
            boxes, scores, classes = out[0][0], out[1][0], out[2][0]
            dets = []
            for b, s, c in zip(boxes, scores, classes):
                if s < threshold:
                    continue
                label = LABELS[int(c)] if int(c) < len(LABELS) else str(int(c))
                x, y, bw, bh = imx500.convert_inference_coords(b, md, picam2)
                dets.append((label, float(s), (int(x), int(y), int(bw), int(bh))))
            bottles = [d for d in dets if d[0] == "bottle"]
            if bottles:
                with_bottle += 1
                best = max(best, max(d[1] for d in bottles))
            picam2.set_overlay(box_overlay((480, 640), dets))
            now = time.time() - t0
            if now - last_print >= 0.5:
                last_print = now
                shown = [f"{l} {s:.2f} @({x},{y} {bw}x{bh})" for l, s, (x, y, bw, bh) in dets
                         if l in WATCH or l == "person"]
                print(f"{now:5.1f}s  " + (" | ".join(shown) if shown else "-"), flush=True)
    finally:
        picam2.stop()
        picam2.close()
    pct = 100.0 * with_bottle / max(frames, 1)
    print(f"SUMMARY: {frames} frames, bottle seen in {with_bottle} ({pct:.0f} %), best score {best:.2f}, "
          f"threshold {threshold}")


if __name__ == "__main__":
    main()
