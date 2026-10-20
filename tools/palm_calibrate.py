"""Palm-direction calibration: measures which hand reading tells 'palm towards the body' apart from
'fist turned outward' on YOUR camera, so the palm check can use the cue that really works.

Run on the Pi (with the monitor):   python3 tools/palm_calibrate.py --camera 0
Stand facing the camera like for a normal curl. Follow the text on screen: for each position, hold the
RIGHT arm straight down with a clenched fist for 5 seconds. Keep the left arm out of the way.
At the end a table is printed and the readings are saved to ~/palm_calib.csv."""

import argparse
import csv
import math
import os
import statistics
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fitform import config                     # noqa: E402
from fitform.camera_thread import CameraStream  # noqa: E402
from fitform.hand_check import HandChecker      # noqa: E402
from fitform.pose_engine import PoseEngine      # noqa: E402
from fitform import palm_calib                  # noqa: E402

POSITIONS = [
    ("inward", "Fist, palm facing your BODY (thigh)"),
    ("front", "Fist, palm facing FORWARD (to the camera)"),
    ("outward", "Fist turned OUTWARD (palm away from body)"),
    ("back", "Fist, palm facing BACKWARD (behind you)"),
    ("inward2", "AGAIN: fist, palm facing your BODY"),
    ("outward2", "AGAIN: fist turned OUTWARD"),
]
FEATURES = list(palm_calib.FEATURES) + ["handed_match"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="0")
    ap.add_argument("--arm", default="right", choices=["right", "left"])
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--check", action="store_true", help="only re-check the saved ~/palm_calib.csv")
    args = ap.parse_args()
    out = os.path.expanduser("~/palm_calib.csv")
    if args.check:
        report(out)
        return
    src = "picam" if args.camera == "picam" else int(args.camera)
    stream = CameraStream(src, config.CAPTURE_WIDTH, config.CAPTURE_HEIGHT)
    if not stream.is_opened():
        print("could not open the camera")
        return
    stream.start()
    W, H = config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT
    pose, hands = PoseEngine(), HandChecker(every_n=1)
    rows, last_id = [], -1
    expected_label = "Left" if args.arm == "right" else "Right"   # MediaPipe assumes a mirrored image
    try:
        for key, text in POSITIONS:
            for phase, dur in (("Get ready", 4.0), ("HOLD", args.seconds)):
                t0 = time.time()
                while time.time() - t0 < dur:
                    fid, frame = stream.read()
                    if frame is None or fid == last_id:
                        time.sleep(0.002)
                        continue
                    last_id = fid
                    frame = cv2.resize(frame, (W, H))
                    lm = pose.process(frame)
                    hands.process(frame, lm)
                    b = hands.raw.get(args.arm)
                    if phase == "HOLD" and b is not None and lm is not None:
                        sc = hands.palm_scores.get(args.arm) or (None, None)
                        f = palm_calib.hand_features(b, args.arm, W, H, sc[0], sc[1])
                        hd = hands.handed.get(args.arm)
                        f.update({"pos": key, "front": sc[0], "inward": sc[1],
                                  "label": hands.palms.get(args.arm), "fist": hands.states.get(args.arm),
                                  "handed": hd[0] if hd else None,
                                  "handed_match": (1.0 if hd[0] == expected_label else -1.0) * hd[1] if hd else None})
                        rows.append(f)
                    img = cv2.flip(frame, 1)
                    left = dur - (time.time() - t0)
                    col = (0, 200, 255) if phase == "Get ready" else (0, 255, 0)
                    cv2.rectangle(img, (0, 0), (W, 90), (0, 0, 0), -1)
                    cv2.putText(img, text, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
                    cv2.putText(img, f"{phase}  {left:.0f} s   ({args.arm.upper()} arm straight down)",
                                (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.75, col, 2)
                    if b is None:
                        cv2.putText(img, "hand not seen", (10, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    cv2.imshow("Palm calibration", img)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        raise KeyboardInterrupt
            print(f"done: {text}")
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
        cv2.destroyAllWindows()

    cols = ["pos", "label", "fist", "handed"] + FEATURES
    with open(out, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    print(f"\nsaved {len(rows)} readings to {out}\n")
    print("position   n   " + "  ".join(f"{c:>12}" for c in FEATURES) + "   labels")
    for key, _ in POSITIONS:
        sel = [r for r in rows if r["pos"] == key]
        if not sel:
            print(f"{key:9} 0   (hand not seen)")
            continue
        med = []
        for c in FEATURES:
            vals = [r[c] for r in sel if r[c] is not None]
            med.append(f"{statistics.median(vals):+12.2f}" if vals else f"{'-':>12}")
        labs = {}
        for r in sel:
            labs[r["label"]] = labs.get(r["label"], 0) + 1
        print(f"{key:9} {len(sel):3d}  " + "  ".join(med) + "   " + " ".join(f"{k}:{v}" for k, v in labs.items()))

    report(out)


def report(path):
    """How each recorded reading is classified by the calibration (rows = what you held)."""
    rows = palm_calib.read_rows(path)
    model, table = palm_calib.check(rows, config.PALM_CALIB_MARGIN)
    if model is None:
        print("\ncalibration incomplete: every position needs at least 3 readings - run it again")
        return
    cls = list(palm_calib.CLASSES) + ["side"]
    print("\nCHECK  (rows = position you held, columns = what the palm check would say)")
    print("held        " + "".join(f"{c:>9}" for c in cls) + "   correct")
    for held in palm_calib.CLASSES:
        t = table.get(held, {})
        n = sum(t.values()) or 1
        ok = sum(v for k, v in t.items() if (k in palm_calib.GOOD) == (held in palm_calib.GOOD) and k != "side")
        print(f"{held:10}  " + "".join(f"{t.get(c, 0):9d}" for c in cls) + f"   {100 * ok / n:5.0f}%")
    print("(correct = good position read as good, wrong position read as wrong; 'side' = unclear, ignored)")


if __name__ == "__main__":
    main()
