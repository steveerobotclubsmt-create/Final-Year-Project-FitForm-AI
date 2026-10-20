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


REASON_TEXT = {
    "elbow": "elbow moved",
    "wrist": "wrist bent",
    "palm": "palm open (clench your fist)",
    "palm_dir": "palm facing away (turn your palm to the front)",
    "fast": "too fast (lift slower)",
    "slow": "too slow",
}
REASON_ORDER = ("elbow", "wrist", "palm_dir", "palm", "fast", "slow")


class BicepCurlCounter:
    """Counts reps for one arm. A rep only counts if form stayed good for the whole rep:
    the upper arm stays where it was at the start, the wrist stays straight, the palm faces the
    front at the bottom (standard curl), and the lift is not too fast or too slow."""

    def __init__(self, arm, alpha=config.SMOOTHING_ALPHA):
        self.arm = arm
        self.alpha = alpha
        self.count = 0
        self.stage = None          # None (not ready yet), "down" or "up"
        self.ready = False         # True once the arm has been held straight (start position)
        self.form_ok = True
        self.attempted = 0         # every completed curl, good or bad
        self.rep_times = []        # seconds per counted rep (lifting time)
        self.last_reasons = []     # why the last rejected rep did not count
        self.last_up_time = None   # lifting time of the last finished curl, for debugging
        self._rep_start = None
        self._straight_since = None
        self._last_seen = None
        self._smooth = {}
        self._base_vec = None      # upper-arm direction while the arm hangs straight
        self._reasons = set()
        self._fist_frames = 0
        self._open_frames = 0
        self._palm_front = 0
        self._palm_back = 0
        self.hand = None
        self.palm = None
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

    def _start_rep(self, now):
        self.form_ok = True
        self._rep_start = now
        self._reasons = set()
        self._fist_frames = self._open_frames = 0
        self._palm_front = self._palm_back = 0

    def update(self, m, now, hand=None, palm=None):
        """Feed one frame of measurements, the hand state ('fist', 'open', 'partial' or None) and the
        palm direction ('front', 'back', 'side' or None). Returns 'counted', 'rejected' or None."""
        if m.get("elbow") is None:
            return None
        # Arm out of view for a while (person walked away): ask for the start position again.
        if self._last_seen is not None and now - self._last_seen > config.ARM_LOST_RESET_SECONDS:
            self.ready, self.stage, self._straight_since = False, None, None
        self._last_seen = now

        elbow = self._ema("elbow", m["elbow"])
        wrist = self._ema("wrist", m.get("wrist"))
        upper = self._ema("upper_vec", m.get("upper_vec"))
        self.hand, self.palm = hand, palm

        straight = elbow > config.DOWN_ANGLE
        if straight:
            if self._straight_since is None:
                self._straight_since = now
            if not self.ready and now - self._straight_since >= config.READY_HOLD_SECONDS:
                self.ready = True
        else:
            self._straight_since = None

        # Remember where the upper arm is while the arm is straight (start of each rep).
        if upper is not None and straight:
            if self._base_vec is None or len(self._base_vec) != len(upper):
                self._base_vec = list(upper)
            else:
                self._base_vec = [0.8 * b + 0.2 * u for b, u in zip(self._base_vec, upper)]
        drift = vector_angle(upper, self._base_vec) if (upper is not None and self._base_vec is not None) else None

        elbow_swinging = drift is not None and drift > config.UPPER_ARM_DRIFT_MAX
        wrist_bent = wrist is not None and wrist < config.WRIST_STRAIGHT_MIN
        palm_open = config.FIST_CHECK and hand == "open"
        palm_away = config.PALM_CHECK and palm == "back" and elbow > config.PALM_CHECK_ELBOW_MIN
        # Hint only: arm is being lowered but has not reached full extension yet.
        not_extended = self.stage == "up" and elbow < config.EXTENSION_MIN_ANGLE

        event = None
        if straight and self.ready:
            # Arm fully straight: every new attempt starts here with a clean slate, so a
            # half rep that went wrong does not carry its fault into the next proper rep.
            self._start_rep(now)
            self.stage = "down"

        if self.stage == "down":
            # palm direction is judged in the lower part of the rep, where front/back is clear
            if palm in ("front", "back") and elbow > config.PALM_CHECK_ELBOW_MIN:
                if palm == "front":
                    self._palm_front += 1
                else:
                    self._palm_back += 1
            # the rest of the form is judged while the arm is actually curling
            if not straight:
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
            up_time = now - self._rep_start if self._rep_start is not None else None
            self.last_up_time = up_time
            if config.FIST_CHECK:
                mostly_open = self._open_frames >= config.OPEN_PALM_MIN_FRAMES and self._open_frames > self._fist_frames
                never_fist = config.FIST_STRICT and self._fist_frames == 0
                if mostly_open or never_fist:
                    self._reasons.add("palm")
            if config.PALM_CHECK and self._palm_back >= config.PALM_AWAY_MIN_FRAMES and self._palm_back > self._palm_front:
                self._reasons.add("palm_dir")
            if up_time is not None and up_time < config.MIN_UP_SECONDS:
                self._reasons.add("fast")
            if up_time is not None and up_time > config.MAX_UP_SECONDS:
                self._reasons.add("slow")
            if self._reasons:
                self.form_ok = False
            if self.form_ok:
                self.count += 1
                if up_time is not None:
                    self.rep_times.append(up_time)
                event = "counted"
            else:
                self.last_reasons = [REASON_TEXT[r] for r in REASON_ORDER if r in self._reasons]
                event = "rejected"

        self.last = {
            "elbow_angle": elbow, "drift": drift, "wrist_angle": wrist, "hand": hand, "palm": palm,
            "elbow_swinging": elbow_swinging, "wrist_bent": wrist_bent, "palm_open": palm_open,
            "palm_away": palm_away, "not_extended": not_extended, "not_ready": not self.ready,
        }
        return event

    def reset(self):
        self.__init__(self.arm, self.alpha)
