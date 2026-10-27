"""'Holding a weight / empty hand' check: a small CNN (MobileNetV3-Small, fine-tuned on hand pictures from
labelled clips, see tools/train_hand_classifier.py) looks at a square picture around each hand.
It runs through OpenCV's DNN module, so FitForm needs no PyTorch. hand_crop() is shared with
tools/hand_crops.py, so the pictures in the app are cut exactly like the training pictures."""

import os

import cv2
import numpy as np

from . import config
from .bicep_curl import ARMS

CROP_SIZE = 128
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)   # ImageNet normalisation used in training
_STD = np.array([0.229, 0.224, 0.225], np.float32)


def hand_crop(frame, lm, arm, size=CROP_SIZE):
    """Square picture of one hand (just past the wrist, along the forearm, scaled to the body's size) from an
    un-mirrored frame and MediaPipe pose landmarks; None if the arm is not clearly seen, the other hand is
    inside the square (its object would be mistaken for this hand's) or the square is mostly off the picture."""
    h, w = frame.shape[:2]
    idx = ARMS[arm]
    e, wr = lm[idx["elbow"]], lm[idx["wrist"]]
    if min(e.visibility, wr.visibility) < 0.6:
        return None
    ex, ey, wx, wy = e.x * w, e.y * h, wr.x * w, wr.y * h
    fore = np.hypot(wx - ex, wy - ey)
    sw = np.hypot((lm[11].x - lm[12].x) * w, (lm[11].y - lm[12].y) * h)
    half = max(24.0, 0.55 * max(fore, 0.5 * sw)) / 2 * 1.6
    if fore > 1:
        cx, cy = wx + 0.35 * (wx - ex) / fore * half, wy + 0.35 * (wy - ey) / fore * half
    else:
        cx, cy = wx, wy
    other = lm[ARMS["left" if arm == "right" else "right"]["wrist"]]
    if other.visibility > 0.3 and max(abs(other.x * w - cx), abs(other.y * h - cy)) < 1.2 * half:
        return None
    x0, y0, x1, y1 = int(cx - half), int(cy - half), int(cx + half), int(cy + half)
    inside = max(0, min(x1, w) - max(x0, 0)) * max(0, min(y1, h) - max(y0, 0))
    if inside < 0.75 * (x1 - x0) * (y1 - y0):
        return None
    pad = max(0, -x0, -y0, x1 - w, y1 - h)
    if pad:
        frame = cv2.copyMakeBorder(frame, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
        x0, y0, x1, y1 = x0 + pad, y0 + pad, x1 + pad, y1 + pad
    return cv2.resize(frame[y0:y1, x0:x1], (size, size), interpolation=cv2.INTER_AREA)


class HoldClassifier:
    """Per arm: 'holding', 'empty' or None (hand not usable this frame). Runs every HOLD_EVERY_N frames."""

    def __init__(self, model_path=None, every_n=None):
        path = model_path or config.HOLD_MODEL
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
        self.net = cv2.dnn.readNetFromONNX(path)
        self.every_n = max(1, every_n or config.HOLD_EVERY_N)
        self._frame = 0
        self.states = {"right": None, "left": None}
        self.probs = {"right": None, "left": None}     # P(holding), for --debug

    def prob_holding(self, crop_bgr):
        x = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = ((x - _MEAN) / _STD).transpose(2, 0, 1)[None]
        self.net.setInput(np.ascontiguousarray(x, np.float32))
        out = self.net.forward()[0]
        e = np.exp(out - out.max())
        return float(e[1] / e.sum())

    def process(self, frame_bgr, pose_landmarks):
        """frame_bgr: the un-mirrored frame given to the pose model. Returns {'right': ..., 'left': ...}."""
        self._frame += 1
        if self._frame % self.every_n:
            return {"right": None, "left": None}      # no new reading on skipped frames
        states = {"right": None, "left": None}
        probs = {"right": None, "left": None}
        if pose_landmarks is not None:
            for arm in ARMS:
                crop = hand_crop(frame_bgr, pose_landmarks.landmark, arm)
                if crop is None:
                    continue
                p = self.prob_holding(crop)
                probs[arm] = p
                states[arm] = "holding" if p >= 0.5 else "empty"
        self.states, self.probs = states, probs
        return states
