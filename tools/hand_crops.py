"""Cuts labelled hand pictures out of the clips from `record_clips.py hands <round>` for training the
'holding a weight / empty hand' classifier (tools/train_hand_classifier.py).
  python tools/hand_crops.py 1 2          # rounds to process (default: every round found)
  python tools/hand_crops.py 2 --front-only    # the webcam was not at the side in that round: skip it
Labels come from the clip name: bottleN -> right hand holding, left empty; bottleLN -> left holding, right empty;
fistN / openN -> both empty. The pose model finds each wrist; the square around the hand (just past the wrist,
along the forearm) is saved as logs/hand_crops/<round>/<holding|empty>/<clip>_<camera>_<arm>_<frame>.jpg.
Front camera: both arms. Side camera: only the arm it is next to (config / --side-arm, default right)."""

import glob
import os
import re
import sys

import cv2
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fitform import config                    # noqa: E402
from fitform.hold_check import hand_crop     # noqa: E402  (same crop as in the app)
from fitform.pose_engine import PoseEngine    # noqa: E402

SIZE = 128            # saved crop size (pixels)
EVERY_N = 2           # use every 2nd frame (neighbouring frames are almost the same picture)
SIDE_ARM = "right"
CLIP = re.compile(r"^(bottleL|bottle|fist|open)(\d+)$")


def labels_for(kind):
    if kind == "bottle":
        return {"right": "holding", "left": "empty"}
    if kind == "bottleL":
        return {"right": "empty", "left": "holding"}
    return {"right": "empty", "left": "empty"}


def process(path, camera, labels, arms, out_dir, name, rotate):
    eng = PoseEngine()
    cap = cv2.VideoCapture(path)
    i = saved = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        i += 1
        if i % EVERY_N:
            continue
        if rotate is not None:
            frame = cv2.rotate(frame, rotate)
        frame = cv2.resize(frame, (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT))
        lm = eng.process(frame)
        if lm is None:
            continue
        for arm in arms:
            crop = hand_crop(frame, lm.landmark, arm, SIZE)
            if crop is None:
                continue
            d = os.path.join(out_dir, labels[arm])
            os.makedirs(d, exist_ok=True)
            cv2.imwrite(os.path.join(d, f"{name}_{camera}_{arm}_{i:05d}.jpg"), crop)
            saved += 1
    eng.close()
    return saved


def main():
    clip_dir = os.path.join(ROOT, config.LOG_DIR, "clips")
    front_only = "--front-only" in sys.argv          # the webcam was not at the side in this round (round 2)
    wanted = set(a for a in sys.argv[1:] if not a.startswith("--"))
    front_rot = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(config.PICAM_ROTATE)
    side_rot = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(config.WEBCAM_ROTATE)
    for front in sorted(glob.glob(os.path.join(clip_dir, "*_front.mp4"))):
        name = os.path.basename(front)[:-len("_front.mp4")]
        m = CLIP.match(name)
        if not m or (wanted and m.group(2) not in wanted):
            continue
        kind, rnd = m.groups()
        labels = labels_for(kind)
        out_dir = os.path.join(ROOT, config.LOG_DIR, "hand_crops", rnd)
        n = process(front, "front", labels, ("right", "left"), out_dir, name, front_rot)
        side = front.replace("_front.mp4", "_side.mp4")
        ns = process(side, "side", labels, (SIDE_ARM,), out_dir, name, side_rot) \
            if os.path.exists(side) and not front_only else 0
        print(f"{name}: {n} front + {ns} side crops (right={labels['right']}, left={labels['left']})")
    for rnd in sorted(os.listdir(os.path.join(ROOT, config.LOG_DIR, "hand_crops"))):
        base = os.path.join(ROOT, config.LOG_DIR, "hand_crops", rnd)
        counts = {c: len(os.listdir(os.path.join(base, c))) for c in sorted(os.listdir(base))}
        print(f"round {rnd}: {counts}")


if __name__ == "__main__":
    main()
