"""Position check before the first rep: is the person standing where the camera can judge their curls?

Uses only the pose landmarks (positions 0..1 in the un-mirrored picture, and how clearly each point is seen).
Limits measured on 15 Nov: recorded clips with good framing (5 clips, 1847 pictures) against a screen recording
where the user stood too close with the head cut off:
                                  good framing      too close
  hips seen (visibility)          0.99 - 1.00       0.06 - 0.18
  shoulder width (share of width) 0.19 - 0.22       0.31 - 0.51
  lowest wrist (1.0 = bottom)     0.30 - 0.78       1.07 - 1.23  (below the picture)
  shoulder width / torso length   0.61 - 0.73       (turned sideways makes it smaller)
  shoulder centre x               0.41 - 0.64
With the head cut off the pose model also invents a face (nose 'seen' 0.99 with no head in the picture) and
loses the person in 4 of 5 pictures, so the head check alone cannot be trusted: the position must also pass the
checks a made-up pose fails (hips, a sensible shoulder width, wrists in the picture), steadily for
POSITION_HOLD_SECONDS."""

from . import config

# (key, checklist label) in the order they are shown; the first failing one gives the instruction
ITEMS = (("body", "Upper body in view"), ("head", "Head in view"), ("hands", "Both hands in view"),
         ("facing", "Facing the camera"), ("distance", "Distance"), ("centre", "In the middle"))

ADVICE = {
    "too_close": "Step back so your whole upper body is in view",
    "head": "Step back so your head is in view",
    "hands": "Keep both hands in view, arms down by your sides",
    "too_far": "Come a little closer",
    "left": "Move a little to your left",
    "right": "Move a little to your right",
    "turned": "Turn to face the camera",
}

NOSE, L_EYE, R_EYE = 0, 2, 5
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP = 11, 12, 13, 14, 15, 16, 23, 24


def check_position(lm, aspect=4 / 3):
    """lm: MediaPipe pose landmarks (list of points with x, y, visibility) or None.
    Returns {'items': [(label, ok)], 'problem': key or None, 'advice': text or None} or None (nobody there)."""
    if lm is None:
        return None
    v = config.POSITION_VISIBILITY
    seen = lambda *ids: all(lm[i].visibility >= v for i in ids)
    sw = abs(lm[L_SH].x - lm[R_SH].x)                                   # share of the picture's width
    sh_y = (lm[L_SH].y + lm[R_SH].y) / 2
    hip_y = (lm[L_HIP].y + lm[R_HIP].y) / 2
    torso = (hip_y - sh_y) / aspect                                      # in picture-width units
    centre = (lm[L_SH].x + lm[R_SH].x) / 2

    hips = seen(L_HIP, R_HIP) and hip_y <= 1.0
    body_ok = hips and sw <= config.POSITION_MAX_SHOULDER_WIDTH
    facing_ok = torso > 0 and sw / torso >= config.POSITION_MIN_FACING_RATIO
    # a real head: the nose sits 0.53-0.74 shoulder widths above the shoulders (good framing, 15 Nov); a face the
    # model invents when the head is cut off lands anywhere (-5 to 16), though not always outside this range.
    # Turned sideways the shoulders look narrow, so then the torso length is the ruler (real head 0.38-0.52).
    neck = sh_y - lm[NOSE].y
    if facing_ok:
        rel, lo, hi = neck / aspect / sw, config.POSITION_NECK_MIN, config.POSITION_NECK_MAX
    else:
        rel, lo, hi = (neck / (hip_y - sh_y) if hip_y > sh_y else 0.0), config.POSITION_NECK_TORSO_MIN, \
            config.POSITION_NECK_TORSO_MAX
    head_ok = seen(NOSE, L_EYE, R_EYE) and lm[NOSE].y >= config.POSITION_MIN_NOSE_Y and lo <= rel <= hi
    hands_ok = (seen(L_EL, R_EL, L_WR, R_WR) and max(lm[L_WR].y, lm[R_WR].y) <= 0.97
                and min(lm[L_WR].x, lm[R_WR].x) >= 0.01 and max(lm[L_WR].x, lm[R_WR].x) <= 0.99)
    dist_ok = config.POSITION_MIN_SHOULDER_WIDTH <= sw <= config.POSITION_MAX_SHOULDER_WIDTH
    centre_ok = config.POSITION_CENTRE_MIN <= centre <= config.POSITION_CENTRE_MAX

    ok = {"body": body_ok, "head": head_ok, "hands": hands_ok, "distance": dist_ok, "centre": centre_ok,
          "facing": facing_ok}
    problem = None
    if not body_ok:
        problem = "too_close"
    elif not head_ok:
        problem = "head"
    elif not hands_ok:
        problem = "hands"
    elif not facing_ok:
        problem = "turned"                        # before distance: turning makes the shoulders look narrow
    elif not dist_ok:
        problem = "too_far"                       # (too close is caught by 'Upper body in view')
    elif not centre_ok:
        # un-mirrored picture: the person's right side is on the picture's left, so someone on the picture's
        # left stands too far to their own right and must move to their left
        problem = "left" if centre < config.POSITION_CENTRE_MIN else "right"
    return {"items": [(label, ok[key]) for key, label in ITEMS], "problem": problem,
            "advice": ADVICE.get(problem)}


class PositionGate:
    """Passes once the position has been good continuously for `hold` seconds; then stays passed until reset()
    (end of the session, or nobody there any more). Curls before it passes are not counted."""

    def __init__(self, hold=None):
        self.hold = config.POSITION_HOLD_SECONDS if hold is None else hold
        self.passed = False
        self.passed_at = None
        self._good_since = None

    def update(self, result, now):
        """result: from check_position(). Returns True on the frame the gate passes."""
        if self.passed:
            return False
        if result is None or result["problem"] is not None:
            self._good_since = None
            return False
        if self._good_since is None:
            self._good_since = now
        if now - self._good_since >= self.hold:
            self.passed, self.passed_at = True, now
            return True
        return False

    def progress(self, now):
        """0..1: how far through the hold time a good position is (for the screen)."""
        if self.passed:
            return 1.0
        if self._good_since is None:
            return 0.0
        return min(1.0, (now - self._good_since) / self.hold) if self.hold > 0 else 1.0

    def reset(self):
        self.passed, self.passed_at, self._good_since = False, None, None


class DriftWatch:
    """During a session: the position problem that has lasted at least `hold` seconds, or None. Curls keep
    counting - this only warns (moving a little during a set is normal)."""

    def __init__(self, hold=None):
        self.hold = config.POSITION_DRIFT_SECONDS if hold is None else hold
        self._key, self._since = None, None

    def update(self, result, now):
        key = result["problem"] if result else None
        if key != self._key:
            self._key, self._since = key, now
        return key if key is not None and now - self._since >= self.hold else None

    def reset(self):
        self._key, self._since = None, None
