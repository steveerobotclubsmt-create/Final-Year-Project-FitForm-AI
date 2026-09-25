"""Joint-angle maths and the strict rep-counting state machine for one arm.

The counter works on three measurements taken from the camera image:
  elbow - elbow flexion angle (180 = straight arm, small = fully curled)
  swing - elbow-shoulder-hip angle (elbow moving away from the torso)
  wrist - wrist straightness (180 = straight)"""

import numpy as np

from . import config

# MediaPipe landmark indices (person's own left/right)
ARMS = {
    "right": {"shoulder": 12, "elbow": 14, "wrist": 16, "hip": 24, "index": 20},
    "left":  {"shoulder": 11, "elbow": 13, "wrist": 15, "hip": 23, "index": 19},
}


def get_angle(a, b, c):
    """2D angle at point b (degrees, 0-180) formed by points a-b-c."""
    a, b, c = np.array(a), np.array(b), np.array(c)
    radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    angle = abs(np.degrees(radians))
    if angle > 180.0:
        angle = 360 - angle
    return round(float(angle), 2)



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
    """Measurements for one arm from its image points."""
    return {
        "elbow": get_angle(pts["shoulder"], pts["elbow"], pts["wrist"]),
        "swing": get_angle(pts["elbow"], pts["shoulder"], pts["hip"]),
        "wrist": get_angle(pts["elbow"], pts["wrist"], pts["index"]),
    }


class BicepCurlCounter:
    """Counts reps for one arm. A rep only counts if form stayed good for the whole rep."""

    def __init__(self, arm, alpha=config.SMOOTHING_ALPHA):
        self.arm = arm
        self.alpha = alpha
        self.count = 0
        self.stage = None          # "down" or "up"
        self.form_ok = True
        self.attempted = 0         # every completed curl, good or bad
        self.rep_times = []        # seconds per counted rep
        self._rep_start = None
        self._smooth = {}
        self.last = {}             # latest measurements + form flags, for display/feedback

    def _ema(self, key, value):
        if value is None:
            self._smooth.pop(key, None)
            return None
        prev = self._smooth.get(key)
        value = value if prev is None else self.alpha * value + (1 - self.alpha) * prev
        self._smooth[key] = value
        return round(value, 2)

    def update(self, m, now):
        """Feed one frame of measurements. Returns 'counted', 'rejected' or None."""
        if m.get("elbow") is None:
            return None
        elbow = self._ema("elbow", m["elbow"])
        swing = self._ema("swing", m.get("swing"))
        wrist = self._ema("wrist", m.get("wrist"))

        elbow_swinging = swing is not None and swing > config.TORSO_SWING_MAX
        wrist_bent = wrist is not None and wrist < config.WRIST_STRAIGHT_MIN
        # Hint only: arm is being lowered but has not reached full extension yet.
        # A rep can only start from full extension anyway (stage must become "down").
        not_extended = self.stage == "up" and elbow < config.EXTENSION_MIN_ANGLE

        if elbow_swinging or wrist_bent:
            self.form_ok = False

        event = None
        if elbow > config.DOWN_ANGLE:
            if self.stage != "down":
                self.form_ok = True          # fresh start for the next rep
                self._rep_start = now
            self.stage = "down"

        if elbow < config.UP_ANGLE and self.stage == "down":
            self.stage = "up"
            self.attempted += 1
            if self.form_ok:
                self.count += 1
                if self._rep_start is not None:
                    self.rep_times.append(now - self._rep_start)
                event = "counted"
            else:
                event = "rejected"

        self.last = {
            "elbow_angle": elbow, "swing": swing, "wrist_angle": wrist,
            "elbow_swinging": elbow_swinging, "wrist_bent": wrist_bent, "not_extended": not_extended,
        }
        return event

    def reset(self):
        self.__init__(self.arm, self.alpha)
