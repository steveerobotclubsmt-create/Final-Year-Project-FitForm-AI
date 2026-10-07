"""Joint-angle maths and the strict rep-counting state machine for one arm.

Measurements per frame (from MediaPipe 3D world landmarks when available, otherwise 2D image points):
  elbow     - elbow flexion angle (180 = straight arm, small = fully curled)
  wrist     - wrist straightness, elbow-wrist-index angle (180 = straight)
  upper_vec - shoulder->elbow direction; the counter compares it with the direction recorded
              while the arm hung straight, so "elbow moved" works from the front or the side
              and does not need the hips to be visible.
Hand shape (fist / open) comes from MediaPipe Hands, see hand_check.py."""

import math

import numpy as np

from . import config

# MediaPipe Pose landmark indices (person's own left/right)
ARMS = {
    "right": {"shoulder": 12, "elbow": 14, "wrist": 16, "hip": 24, "index": 20},
    "left":  {"shoulder": 11, "elbow": 13, "wrist": 15, "hip": 23, "index": 19},
}


def get_angle(a, b, c):
    """Angle at point b (degrees, 0-180) formed by points a-b-c. Works for 2D or 3D points."""
    a, b, c = np.array(a, float), np.array(b, float), np.array(c, float)
    v1, v2 = a - b, c - b
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    if n == 0:
        return 180.0
    cosang = np.clip(np.dot(v1, v2) / n, -1.0, 1.0)
    return round(float(np.degrees(np.arccos(cosang))), 2)


def vector_angle(u, v):
    """Angle in degrees between two direction vectors (2D or 3D)."""
    u, v = np.array(u, float), np.array(v, float)
    n = np.linalg.norm(u) * np.linalg.norm(v)
    if n == 0:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(np.dot(u, v) / n, -1.0, 1.0))))


def arm_visibility(landmarks, arm):
    idx = ARMS[arm]
    return min(landmarks[idx[j]].visibility for j in ("shoulder", "elbow", "wrist"))


def arm_points(landmarks, arm, width, height):
    """Mirrored pixel coordinates for one arm, or None if the arm is not clearly visible."""
    idx = ARMS[arm]
    if arm_visibility(landmarks, arm) <= config.LANDMARK_VISIBILITY_MIN:
        return None
    return {joint: [width - int(landmarks[i].x * width), int(landmarks[i].y * height)]
            for joint, i in idx.items()}


def measure_from_points(pts):
    """Measurements for one arm from 2D image points."""
    s, e = pts["shoulder"], pts["elbow"]
    return {
        "elbow": get_angle(pts["shoulder"], pts["elbow"], pts["wrist"]),
        "wrist": get_angle(pts["elbow"], pts["wrist"], pts["index"]),
        "upper_vec": [e[0] - s[0], e[1] - s[1]],
    }


def measure_from_world(world_landmarks, arm):
    """Measurements for one arm from MediaPipe 3D world landmarks (metres, view-independent)."""
    idx = ARMS[arm]
    p = {j: [world_landmarks[i].x, world_landmarks[i].y, world_landmarks[i].z] for j, i in idx.items()}
    s, e = p["shoulder"], p["elbow"]
    return {
        "elbow": get_angle(p["shoulder"], p["elbow"], p["wrist"]),
        "wrist": get_angle(p["elbow"], p["wrist"], p["index"]),
        "upper_vec": [e[0] - s[0], e[1] - s[1], e[2] - s[2]],
    }


REASON_TEXT = {"elbow": "elbow moved", "wrist": "wrist bent", "palm": "palm open (clench your fist)"}


class BicepCurlCounter:
    """Counts reps for one arm. A rep only counts if form stayed good for the whole rep:
    the upper arm stays where it was at the start, the wrist stays straight and the hand is a fist."""

    def __init__(self, arm, alpha=config.SMOOTHING_ALPHA):
        self.arm = arm
        self.alpha = alpha
        self.count = 0
        self.stage = None          # "down" or "up"
        self.form_ok = True
        self.attempted = 0         # every completed curl, good or bad
        self.rep_times = []        # seconds per counted rep
        self.last_reasons = []     # why the last rejected rep did not count
        self._rep_start = None
        self._smooth = {}
        self._base_vec = None      # upper-arm direction while the arm hangs straight
        self._reasons = set()
        self._fist_frames = 0
        self._open_frames = 0
        self.hand = None
        self.last = {}             # latest measurements + form flags, for display/feedback

    def _ema(self, key, value):
        if value is None:
            self._smooth.pop(key, None)
            return None
        prev = self._smooth.get(key)
        if isinstance(value, (list, tuple)):
            value = list(value) if prev is None else [self.alpha * v + (1 - self.alpha) * p for v, p in zip(value, prev)]
            self._smooth[key] = value
            return value
        value = value if prev is None else self.alpha * value + (1 - self.alpha) * prev
        self._smooth[key] = value
        return round(value, 2)

    def update(self, m, now, hand=None):
        """Feed one frame of measurements and the hand state ('fist', 'open', 'partial' or None).
        Returns 'counted', 'rejected' or None."""
        if m.get("elbow") is None:
            return None
        elbow = self._ema("elbow", m["elbow"])
        wrist = self._ema("wrist", m.get("wrist"))
        upper = self._ema("upper_vec", m.get("upper_vec"))
        self.hand = hand

        # Remember where the upper arm is while the arm is straight (start of each rep).
        if upper is not None and elbow > config.DOWN_ANGLE:
            if self._base_vec is None or len(self._base_vec) != len(upper):
                self._base_vec = list(upper)
            else:
                self._base_vec = [0.8 * b + 0.2 * u for b, u in zip(self._base_vec, upper)]
        drift = vector_angle(upper, self._base_vec) if (upper is not None and self._base_vec is not None) else None

        elbow_swinging = drift is not None and drift > config.UPPER_ARM_DRIFT_MAX
        wrist_bent = wrist is not None and wrist < config.WRIST_STRAIGHT_MIN
        palm_open = config.FIST_CHECK and hand == "open"
        # Hint only: arm is being lowered but has not reached full extension yet.
        not_extended = self.stage == "up" and elbow < config.EXTENSION_MIN_ANGLE

        event = None
        if elbow > config.DOWN_ANGLE:
            if self.stage != "down":
                self.form_ok = True          # fresh start for the next rep
                self._rep_start = now
                self._reasons = set()
                self._fist_frames = self._open_frames = 0
            self.stage = "down"

        # Form is judged while the arm is actually curling (between straight and the top).
        if self.stage == "down" and elbow <= config.DOWN_ANGLE:
            if elbow_swinging:
                self._reasons.add("elbow")
            if wrist_bent:
                self._reasons.add("wrist")
            if hand == "fist":
                self._fist_frames += 1
            elif hand == "open":
                self._open_frames += 1
            if elbow_swinging or wrist_bent:
                self.form_ok = False

        if elbow < config.UP_ANGLE and self.stage == "down":
            self.stage = "up"
            self.attempted += 1
            if config.FIST_CHECK:
                mostly_open = self._open_frames >= config.OPEN_PALM_MIN_FRAMES and self._open_frames > self._fist_frames
                never_fist = config.FIST_STRICT and self._fist_frames == 0
                if mostly_open or never_fist:
                    self._reasons.add("palm")
                    self.form_ok = False
            if self.form_ok:
                self.count += 1
                if self._rep_start is not None:
                    self.rep_times.append(now - self._rep_start)
                event = "counted"
            else:
                self.last_reasons = [REASON_TEXT[r] for r in ("elbow", "wrist", "palm") if r in self._reasons]
                event = "rejected"

        self.last = {
            "elbow_angle": elbow, "drift": drift, "wrist_angle": wrist, "hand": hand,
            "elbow_swinging": elbow_swinging, "wrist_bent": wrist_bent, "palm_open": palm_open,
            "not_extended": not_extended,
        }
        return event

    def reset(self):
        self.__init__(self.arm, self.alpha)
