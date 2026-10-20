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
    "fist": "hand open (close your hand)",
    "palm_dir": "hand turned outward",
    "hand_hidden": "hand not visible",
    "fast": "too fast",
    "slow": "too slow",
}
REASON_ORDER = ("hand_hidden", "fist", "palm_dir", "elbow", "wrist", "fast", "slow")


class BicepCurlCounter:
    """Counts reps for one arm.
    1. Down position (arm straight, before the lift): the hand must be seen as a fist with the palm
       facing forward (standard curl). This is the gate - a rep only counts if the start was good.
    2. Lift: elbow movement, bent wrist, wrong hand or a hidden hand reject the rep only if they last
       longer than FAULT_HOLD_SECONDS, so one-frame detection blips do not spoil a good rep.
    3. Tempo: the lift must not be too fast or too slow."""

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
        self.last_up_time = None   # lifting time of the last finished curl
        self.last_hand_summary = ""
        self._rep_start = None
        self._straight_since = None
        self._straight_frames = 0
        self._top_frames = 0
        self._last_seen = None
        self._smooth = {}
        self._base_vec = None      # upper-arm direction while the arm hangs straight
        self._reasons = set()
        self._start_checked = False
        self._fault_since = {}
        self._hand_log = []        # (time, hand state, palm direction, arm straight?)
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

    def _start_position_reasons(self, now):
        """Checks the hand in the down position just before the lift. Returns a set of reason keys."""
        since = (self._rep_start if self._rep_start is not None else now) - config.HAND_WINDOW_BEFORE
        window = [e for e in self._hand_log if e[0] >= since and e[3]]
        reasons, notes = set(), []
        if config.FIST_CHECK:
            seen = [e[1] for e in window if e[1] in ("fist", "open", "partial")]
            closed = sum(1 for h in seen if h != "open")
            notes.append(f"start closed hand {closed}/{len(seen)}")
            if len(seen) < config.HAND_MIN_READINGS:
                reasons.add("hand_hidden")
            elif closed * 2 <= len(seen):
                reasons.add("fist")
        if config.PALM_CHECK:
            seen = [e[2] for e in window if e[2] in ("front", "back", "side")]
            good = ("front", "back") if config.PALM_ALLOW_BACK else ("front",)
            front = sum(1 for p in seen if p in good)
            notes.append(f"start palm facing camera {front}/{len(seen)}")
            if len(seen) < config.HAND_MIN_READINGS:
                reasons.add("hand_hidden")
            elif front < config.PALM_FRONT_MIN_RATIO * len(seen):
                reasons.add("palm_dir")
        self.last_hand_summary = ", ".join(notes)
        return reasons

    def _hold(self, key, on, now):
        """True once fault `key` has been on continuously for longer than FAULT_HOLD_SECONDS."""
        if not on:
            self._fault_since.pop(key, None)
            return False
        since = self._fault_since.setdefault(key, now)
        return now - since >= config.FAULT_HOLD_SECONDS

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

        straight_raw = elbow > config.DOWN_ANGLE
        self._straight_frames = self._straight_frames + 1 if straight_raw else 0
        straight = self._straight_frames >= config.STRAIGHT_CONFIRM_FRAMES
        self._hand_log.append((now, hand, palm, straight_raw))
        keep = config.MAX_UP_SECONDS + config.HAND_WINDOW_BEFORE + 2.0
        while self._hand_log and now - self._hand_log[0][0] > keep:
            self._hand_log.pop(0)

        if straight:
            if self._straight_since is None:
                self._straight_since = now
            if not self.ready and now - self._straight_since >= config.READY_HOLD_SECONDS:
                self.ready = True
        elif not straight_raw:
            self._straight_since = None

        # Remember where the upper arm is while the arm is straight (start of each rep).
        if upper is not None and straight_raw:
            if self._base_vec is None or len(self._base_vec) != len(upper):
                self._base_vec = list(upper)
            else:
                self._base_vec = [0.8 * b + 0.2 * u for b, u in zip(self._base_vec, upper)]
        drift = vector_angle(upper, self._base_vec) if (upper is not None and self._base_vec is not None) else None

        hand_checks = config.FIST_CHECK or config.PALM_CHECK
        low = elbow > config.PALM_CHECK_ELBOW_MIN
        elbow_swinging = drift is not None and drift > config.UPPER_ARM_DRIFT_MAX
        wrist_bent = wrist is not None and wrist < config.WRIST_STRAIGHT_MIN
        hand_open = config.FIST_CHECK and hand == "open"
        bad_palm = ("side",) if config.PALM_ALLOW_BACK else ("back", "side")
        palm_away = config.PALM_CHECK and palm in bad_palm and low
        hand_hidden = hand_checks and hand is None and palm is None and low
        # Hint only: arm is being lowered but has not reached full extension yet.
        not_extended = self.stage == "up" and elbow < config.EXTENSION_MIN_ANGLE

        event = None
        if straight and self.ready:
            # Arm fully straight: every new attempt starts here with a clean slate, so a
            # half rep that went wrong does not carry its fault into the next proper rep.
            self.form_ok = True
            self._rep_start = now
            self._reasons = set()
            self._fault_since = {}
            self._start_checked = False
            self.stage = "down"

        if self.stage == "down" and not straight_raw:
            if not self._start_checked:            # the moment the lift begins: was the start good?
                self._reasons |= self._start_position_reasons(now)
                self._start_checked = True
            for key, on in (("elbow", elbow_swinging), ("wrist", wrist_bent), ("fist", hand_open),
                            ("palm_dir", palm_away), ("hand_hidden", hand_hidden)):
                if self._hold(key, on, now):
                    self._reasons.add(key)
            if self._reasons:
                self.form_ok = False

        self._top_frames = self._top_frames + 1 if elbow < config.UP_ANGLE else 0
        if self.stage == "down" and self._top_frames >= config.TOP_CONFIRM_FRAMES:
            self.stage = "up"
            self.attempted += 1
            if not self._start_checked:
                self._reasons |= self._start_position_reasons(now)
            up_time = now - self._rep_start if self._rep_start is not None else None
            self.last_up_time = up_time
            if up_time is not None and up_time < config.MIN_UP_SECONDS:
                self._reasons.add("fast")
            if up_time is not None and up_time > config.MAX_UP_SECONDS:
                self._reasons.add("slow")
            self.form_ok = not self._reasons
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
            "elbow_swinging": elbow_swinging, "wrist_bent": wrist_bent, "hand_open": hand_open,
            "palm_away": palm_away, "not_extended": not_extended, "not_ready": not self.ready,
        }
        return event

    def reset(self):
        self.__init__(self.arm, self.alpha)
