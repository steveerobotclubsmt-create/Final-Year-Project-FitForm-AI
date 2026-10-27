"""Records labelled test clips from both cameras for tuning the rep checks (tempo, lowering, swinging).
The Pi screen shows what to do and counts down, so nobody has to touch the keyboard.
  python tools/record_clips.py                        # the standard set: slow, fast swing, fast drop
  python tools/record_clips.py slow:40 swing:30       # choose clips and seconds yourself
  python tools/record_clips.py hands 1                # hand classifier: bottle right/left, fist, open (round 1)
Files go to logs/clips/ (not uploaded to GitHub):  <label>_front.mp4, <label>_side.mp4, <label>_times.csv
The front clip is saved as the camera sees it (not rotated): replay with
  python main.py --video logs/clips/slow_front.mp4 --rotate 180 --side-camera logs/clips/slow_side.mp4"""

import os
import sys
import time

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fitform import config                           # noqa: E402
from fitform.camera_detect import detect             # noqa: E402
from fitform.camera_thread import CameraStream, _RpicamCapture   # noqa: E402

INSTRUCTIONS = {
    "slow": "SLOW, PROPER curls: about 2 s up, 2-3 s down. Both arms one after the other.",
    "swing": "FAST SWINGS: throw the arm up quickly (the wrong way). Both arms.",
    "drop": "Normal lift, then DROP the arm down fast (the wrong way). Both arms.",
    # hand classifier ('holding a weight' / 'empty'): curl normally; a number after the label is the round (bottle2)
    "bottle": "BOTTLE held FLAT like a dumbbell, in the RIGHT hand. Normal curls; turn it a little now and then.",
    "bottleL": "BOTTLE held FLAT like a dumbbell, in the LEFT hand. Normal curls; turn it a little now and then.",
    "fist": "EMPTY hands, CLENCHED fists. Normal curls, both arms.",
    "open": "EMPTY hands, OPEN or relaxed. Normal curls, both arms.",
}
DEFAULT = [("slow", 45), ("swing", 30), ("drop", 30)]
HANDS = [("bottle", 40), ("bottleL", 40), ("fist", 40), ("open", 40)]   # python tools/record_clips.py hands [round]
GET_READY_S = 12
FIRST_READY_S = 20          # more time before the first clip (walk from the Pi to your place)
FPS = 30


def show(window, frame, lines, rotate):
    img = cv2.rotate(frame, rotate) if rotate is not None else frame.copy()
    img = cv2.flip(cv2.resize(img, (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)), 1)
    y = 40
    for text, col, fs in lines:
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
        fs = min(fs, fs * (img.shape[1] - 20) / max(tw, 1))
        cv2.rectangle(img, (0, y - th - 10), (img.shape[1], y + 10), (15, 15, 15), -1)
        cv2.putText(img, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, fs, col, 2)
        y += th + 26
    cv2.imshow(window, img)
    cv2.waitKey(1)


def main():
    if sys.argv[1:2] == ["hands"]:                   # the hand-classifier set, e.g. 'hands 2' -> bottle2, fist2, ...
        rnd = sys.argv[2] if len(sys.argv) > 2 else "1"
        clips = [(f"{label}{rnd}", s) for label, s in HANDS]
    else:
        clips = [(a.split(":")[0], int(a.split(":")[1]) if ":" in a else 30) for a in sys.argv[1:]] or DEFAULT
    out_dir = os.path.join(ROOT, config.LOG_DIR, "clips")
    os.makedirs(out_dir, exist_ok=True)
    front_src, side_src = detect()
    if front_src != "picam":
        print("ERROR: the AI camera (front) was not found")
        return 1
    front = _RpicamCapture(config.CAPTURE_WIDTH, config.CAPTURE_HEIGHT, FPS)   # read directly: one frame per tick
    side = CameraStream(side_src, config.CAPTURE_WIDTH, config.CAPTURE_HEIGHT).start() if side_src is not None else None
    rotate = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(config.PICAM_ROTATE)
    window = "FitForm - recording test clips"
    orange, white, red, green = (0, 200, 255), (235, 235, 235), (0, 0, 255), (0, 220, 0)
    try:
        for n, (label, seconds) in enumerate(clips, 1):
            what = INSTRUCTIONS.get(label.rstrip("0123456789"), label)
            t0 = time.time()
            ready_s = FIRST_READY_S if n == 1 else GET_READY_S
            while time.time() - t0 < ready_s:                # get ready (not recorded)
                ok, frame = front.read()
                if not ok:
                    return 1
                left = ready_s - (time.time() - t0)
                show(window, frame, [(f"Clip {n}/{len(clips)}: {label.upper()}", orange, 1.0), (what, white, 0.6),
                                     (f"Get in position - recording starts in {left:.0f} s", orange, 0.8)], rotate)
            base = os.path.join(out_dir, label)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            wf = ws = None
            times = open(base + "_times.csv", "w")
            times.write("frame,t\n")
            t0, i = time.time(), 0
            while time.time() - t0 < seconds:
                ok, frame = front.read()
                if not ok:
                    return 1
                now = time.time() - t0
                if wf is None:
                    wf = cv2.VideoWriter(base + "_front.mp4", fourcc, FPS, (frame.shape[1], frame.shape[0]))
                wf.write(frame)
                if side is not None:
                    _, sframe = side.read()
                    if sframe is not None:
                        if ws is None:
                            ws = cv2.VideoWriter(base + "_side.mp4", fourcc, FPS, (sframe.shape[1], sframe.shape[0]))
                        ws.write(sframe)
                times.write(f"{i},{now:.3f}\n")
                i += 1
                show(window, frame, [(f"RECORDING {label.upper()}  {seconds - now:.0f} s", red, 1.0),
                                     (what, white, 0.6)], rotate)
            times.close()
            for w in (wf, ws):
                if w is not None:
                    w.release()
            print(f"[REC] {label}: {i} frames in {seconds} s ({i / seconds:.1f} fps) -> {base}_front.mp4"
                  f"{' + ' + base + '_side.mp4' if ws is not None else ''}")
        t0 = time.time()
        while time.time() - t0 < 3:
            ok, frame = front.read()
            if ok:
                show(window, frame, [("All clips recorded - thank you!", green, 1.0)], rotate)
    finally:
        front.release()
        if side is not None:
            side.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
