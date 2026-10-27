"""Joint-angle maths and the strict rep-counting state machine for one arm.

Measurements per frame (from MediaPipe 3D world landmarks when available, otherwise 2D image points):
  elbow     - elbow flexion angle (180 = straight arm, small = fully curled)
  wrist     - wrist straightness, elbow-wrist-index angle (180 = straight)
  upper_vec - shoulder->elbow direction; the counter compares it with the direction recorded
              while the arm hung straight, so "elbow moved" works from the front or the side
              and does not need the hips to be visible.
Hand shape (fist / open) comes from MediaPipe Hands, see hand_check.py."""


import numpy as np

from . import config
from .hand_state import PALM_ALL, PALM_BAD, PALM_GOOD

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
    "fist": "hand not clenched",
    "palm_dir": "palm turned outward or backward",
    "hand_hidden": "hand not visible",
    "fast": "too fast",
    "slow": "too slow",
    "drop": "lowered too fast",
    "not_lowered": "arm not straightened at the bottom",
    "arm_tilt": "upper arm not pointing down",
    "arm_forward": "elbow moved forward/back",
}
# what the user should do about each problem (shown under the 'Not counted' message)
FIX_TEXT = {
    "elbow": "Keep your elbow still at your side",
    "arm_tilt": "Keep your upper arm pointing down",
    "arm_forward": "Keep your elbow by your side",
    "wrist": "Keep your wrist straight",
    "fist": "Grip the weight firmly",
    "palm_dir": "Keep your palm facing your body",
    "hand_hidden": "Keep your hand in view of the camera",
    "fast": "Lift a little slower",
    "slow": "Lift a little faster",
    "drop": "Lower the weight slowly",
    "not_lowered": "Straighten your arm fully at the bottom",
}
REASON_ORDER = ("arm_tilt", "arm_forward", "elbow", "hand_hidden", "fist", "palm_dir", "wrist", "fast", "slow")


class BicepCurlCounter:
    """Counts reps for one arm.
    1. Down position (arm straight, before the lift): the hand must be seen as a fist with the palm
       facing forward or towards the body. This is the gate - a rep only counts if the start was good.
    2. Lift: elbow movement, bent wrist, wrong hand or a hidden hand reject the rep only if they last
       longer than FAULT_HOLD_SECONDS, so one-frame detection blips do not spoil a good rep.
    3. Tempo: the lift must not be too fast or too slow (timed from the wrist's height when it is known).
    4. Lowering: with MIN_DOWN_SECONDS > 0 a good lift is only counted once the arm is back at the bottom,
       and not if it was dropped faster than that."""

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
        self._hand_log = []        # (time, hand state, palm direction, elbow angle)
        self.blocked_until = 0.0   # after a rejected rep: no new rep until the user has read what was wrong
        self.palm_tip = False      # palm looked turned out during the last rep (advice only, see PALM_REJECTS)
        self.palm_streak = 0       # recent completed reps where a camera saw the fist turned out
        self._palm_hist = []       # turned out yes/no for the last OUTWARD_WINDOW reps
        self.reject_counts = {}    # reason key -> how many curls were not counted for it (session summary)
        self.palm_flags = 0        # curls where a camera saw the fist turned out (session summary)
        self.palm_flag_last = False   # the curl that just finished was one of them (for the hand picture)
        self.grip_flags = 0        # curls where the hand looked open (advisory, see FIST_REJECTS)
        self.grip_flag_last = False
        self.lift_times_all = []   # lift time of every finished curl, counted or not
        self.outward_alert = False # True while the 'fist facing outward' pause is on
        self.reject_key = None     # main reason of the last rejected rep (for the 'what to do' hint)
        self._side_log = []        # (time, side-camera palm label) - only when a side camera is used
        self._rose_since_top = False   # arm went back down after the top without becoming straight
        self._len_ref = None           # upper-arm length / shoulder width at the start of the rep
        self._start_tilt = None
        self._lift_palm = [0, 0]       # [good, bad] palm readings: down position + lower part of the lift
        self._bottom_h = None          # wrist height while the arm hangs straight
        self._leave_t = None           # last time the wrist was at the bottom (start of the lift)
        self._pending = False          # good lift waiting for the lowering check
        self._top_h = None             # highest wrist height of the current top
        self._left_top_t = None        # last time the wrist was at the top (start of the lowering)
        self.last_down_time = None     # lowering time of the last finished rep
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
        # the down position = the lower part of the movement (straight arm and the end of the
        # previous lowering) in the last HAND_WINDOW_BEFORE seconds before the lift
        window = [e for e in self._hand_log if e[0] >= since and e[3] > config.PALM_CHECK_ELBOW_MIN]
        reasons, notes = set(), []
        if config.FIST_CHECK:
            seen = [e[1] for e in window if e[1] in ("fist", "open", "partial")]
            fists = sum(1 for h in seen if h == "fist")
            notes.append(f"start fist {fists}/{len(seen)}")
            if len(seen) < config.HAND_MIN_READINGS:
                reasons.add("hand_hidden")
            elif fists * 2 <= len(seen):
                reasons.add("fist")
        if config.PALM_CHECK:
            # front camera palm direction: only while the arm is (nearly) straight - from about 130 degrees on,
            # a correct fist starts to read 'outward' because the forearm tilts towards the camera (21 Oct log)
            seen = [e[2] for e in window if e[2] in PALM_ALL and e[3] > config.PALM_DIR_ELBOW_MIN]
            if len(seen) < config.HAND_MIN_READINGS and not config.FIST_CHECK:
                reasons.add("hand_hidden")      # (with the fist check on, that check already covers a hidden hand)
            # the down-position readings start the palm vote; the lower part of the lift adds to it and
            # the decision is made once at the top (one vote, so a few noisy readings cannot fail the rep)
            self._lift_palm = [sum(1 for p in seen if p in PALM_GOOD), sum(1 for p in seen if p in PALM_BAD)]
        self.last_hand_summary = ", ".join(notes)
        return reasons

    @staticmethod
    def _advisory():
        """Reasons that are reported but do not stop a rep from counting."""
        return (({"palm_dir"} if not config.PALM_REJECTS else set()) | ({"fist"} if not config.FIST_REJECTS else set())
                | ({"hand_hidden"} if not config.HAND_HIDDEN_REJECTS else set()))

    def _hold(self, key, on, now):
        """True once fault `key` has been on continuously for longer than its hold time."""
        if not on:
            self._fault_since.pop(key, None)
            return False
        since = self._fault_since.setdefault(key, now)
        hold = config.PALM_HOLD_SECONDS if key == "palm_dir" else config.FAULT_HOLD_SECONDS
        return now - since >= hold

    def update(self, m, now, hand=None, palm=None, side_palm=None):
        """Feed one frame of measurements, the hand state ('fist', 'open', 'partial' or None) and the
        palm direction ('front', 'inward', 'outward', 'back', 'side' or None). Returns 'counted', 'rejected' or None."""
        if m.get("elbow") is None:
            return None
        # Arm out of view for a while (person walked away): ask for the start position again.
        if self._last_seen is not None and now - self._last_seen > config.ARM_LOST_RESET_SECONDS:
            self.ready, self.stage, self._straight_since = False, None, None
            self._pending, self._leave_t = False, None
        self._last_seen = now

        elbow = self._ema("elbow", m["elbow"])
        wrist = self._ema("wrist", m.get("wrist"))
        upper = self._ema("upper_vec", m.get("upper_vec"))
        wrist_h = self._ema("wrist_h", m.get("wrist_h"))
        self.hand, self.palm = hand, palm

        # first rep: the arm must be properly straight; later reps restart a little earlier (REARM_ANGLE)
        straight_raw = elbow > (config.DOWN_ANGLE if not self.ready else config.REARM_ANGLE)
        self._straight_frames = self._straight_frames + 1 if straight_raw else 0
        straight = self._straight_frames >= config.STRAIGHT_CONFIRM_FRAMES
        self._hand_log.append((now, hand, palm, elbow))
        if side_palm is not None:
            self._side_log.append((now, side_palm))
            while self._side_log and now - self._side_log[0][0] > config.MAX_UP_SECONDS + config.HAND_WINDOW_BEFORE + 2.0:
                self._side_log.pop(0)
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

        # wrist height: its level with the arm hanging straight, and whether it is there now
        if wrist_h is not None and straight_raw:
            self._bottom_h = wrist_h if self._bottom_h is None else 0.8 * self._bottom_h + 0.2 * wrist_h
        if wrist_h is not None and self._bottom_h is not None:
            at_bottom = wrist_h <= self._bottom_h + config.WRIST_MOVE_MARGIN
        else:
            at_bottom = straight_raw                # no wrist height: fall back to the straight arm
        if at_bottom:
            self._leave_t = now

        event = None
        # Lowering after a good lift: the rep is decided once the arm is back at the bottom.
        if self._pending:
            if wrist_h is not None:
                self._top_h = wrist_h if self._top_h is None else max(self._top_h, wrist_h)
                if wrist_h >= self._top_h - config.WRIST_MOVE_MARGIN:
                    self._left_top_t = now
            elif elbow < config.UP_ANGLE:
                self._left_top_t = now
            if at_bottom:
                self._pending = False
                down = now - self._left_top_t
                self.last_down_time = down
                if down < config.MIN_DOWN_SECONDS:
                    self.form_ok = False
                    self.last_reasons = [REASON_TEXT["drop"]]
                    self.reject_key = "drop"
                    self.reject_counts["drop"] = self.reject_counts.get("drop", 0) + 1
                    self.blocked_until = now + config.REJECT_PAUSE_SECONDS
                    event = "rejected"
                else:
                    event = self._count()

        # Remember where the upper arm is while the arm is straight (start of each rep).
        if upper is not None and straight_raw:
            if self._base_vec is None or len(self._base_vec) != len(upper):
                self._base_vec = list(upper)
            else:
                self._base_vec = [0.8 * b + 0.2 * u for b, u in zip(self._base_vec, upper)]
        drift = vector_angle(upper, self._base_vec) if (upper is not None and self._base_vec is not None) else None

        # Upper arm must point down (2D picture, so this sees tilting to the side or up) ...
        u2 = m.get("upper_vec2d") or (upper if (upper is not None and len(upper) == 2) else None)
        tilt = vector_angle(u2, [0.0, 1.0]) if u2 is not None else None
        # ... and must not swing forward/back: the camera then sees it shorter (relative to shoulder width).
        len_ratio = None
        if m.get("upper_len") and m.get("shoulder_w"):
            r = m["upper_len"] / m["shoulder_w"]
            if straight_raw:
                self._len_ref = r if self._len_ref is None else 0.7 * self._len_ref + 0.3 * r
            if self._len_ref:
                len_ratio = r / self._len_ref
        if straight_raw:
            self._start_tilt = tilt

        arm_tilted = tilt is not None and tilt > config.UPPER_ARM_MAX_TILT
        arm_forward = len_ratio is not None and len_ratio < config.UPPER_ARM_MIN_LENGTH
        hand_checks = config.FIST_CHECK or config.PALM_CHECK
        low = elbow > config.PALM_CHECK_ELBOW_MIN
        elbow_swinging = drift is not None and drift > config.UPPER_ARM_DRIFT_MAX
        wrist_bent = wrist is not None and wrist < config.WRIST_STRAIGHT_MIN
        hand_open = config.FIST_CHECK and hand in ("open", "partial")
        straight_part = elbow > config.PALM_DIR_ELBOW_MIN
        palm_away = config.PALM_CHECK and palm in PALM_BAD and straight_part
        hand_hidden = hand_checks and hand is None and palm is None and low
        # Hint only: arm is being lowered but has not reached full extension yet.
        not_extended = self.stage == "up" and elbow < config.EXTENSION_MIN_ANGLE

        if straight and self.ready and now >= self.blocked_until and not self._pending:
            # Arm fully straight: every new attempt starts here with a clean slate, so a
            # half rep that went wrong does not carry its fault into the next proper rep.
            self.form_ok = True
            self._rep_start = now
            self._reasons = set()
            self._fault_since = {}
            self._start_checked = False
            self._rose_since_top = False
            self._lift_palm = [0, 0]
            self.palm_tip = False
            self.outward_alert = False
            self.stage = "down"

        if self.stage == "down" and not straight_raw:
            if not self._start_checked:            # the moment the lift begins: was the start good?
                self._reasons |= self._start_position_reasons(now)
                if self._start_tilt is not None and self._start_tilt > config.UPPER_ARM_MAX_TILT:
                    self._reasons.add("arm_tilt")
                self._start_checked = True
            elif config.PALM_CHECK and straight_part and palm in PALM_ALL and palm != "side":
                self._lift_palm[1 if palm in PALM_BAD else 0] += 1   # (this frame is already in the start vote)
            for key, on in (("elbow", elbow_swinging), ("arm_tilt", arm_tilted), ("arm_forward", arm_forward),
                            ("wrist", wrist_bent), ("fist", hand_open),
                            ("palm_dir", palm_away), ("hand_hidden", hand_hidden)):
                if self._hold(key, on, now):
                    self._reasons.add(key)
            if self._reasons - self._advisory():
                self.form_ok = False

        # forearm pointing at the camera (mid-lift, facing it): the 2D picture squashes it and the 2D elbow
        # angle jumps (seen 21 Oct: 106 deg read as 2), which ended reps early as 'too fast' - such frames
        # cannot be the top of the rep
        fl, ul = m.get("forearm_len"), m.get("upper_len")
        foreshortened = bool(fl is not None and ul and fl < config.FORESHORTEN_RATIO * ul)
        self._top_frames = self._top_frames + 1 if (elbow < config.UP_ANGLE and not foreshortened) else 0
        # Curled again without straightening the arm in between: tell the user instead of staying silent.
        if self.stage == "up" and now < self.blocked_until:
            self._rose_since_top = False           # pause after a rejected rep: nothing is judged
        elif self.stage == "up":
            if elbow > config.PALM_CHECK_ELBOW_MIN:
                self._rose_since_top = True
            elif self._rose_since_top and self._top_frames >= config.TOP_CONFIRM_FRAMES:
                self._rose_since_top = False
                if self._pending:
                    self._pending = False           # the lift waiting for its lowering becomes this rejection
                else:
                    self.attempted += 1
                self.form_ok = False
                self.last_up_time = None
                self.last_hand_summary = ""
                self.last_reasons = [REASON_TEXT["not_lowered"]]
                self.reject_key = "not_lowered"
                self.reject_counts["not_lowered"] = self.reject_counts.get("not_lowered", 0) + 1
                self.blocked_until = now + config.REJECT_PAUSE_SECONDS
                event = "rejected"
        if self.stage == "down" and self._top_frames >= config.TOP_CONFIRM_FRAMES:
            self.stage = "up"
            self.attempted += 1
            if not self._start_checked:
                self._reasons |= self._start_position_reasons(now)
            # the lift starts when the wrist leaves the bottom (or, without wrist height, when the arm bends)
            start = self._leave_t if (wrist_h is not None and self._leave_t is not None) else self._rep_start
            up_time = now - start if start is not None else None
            self.last_up_time = up_time
            self.last_down_time = None
            if config.PALM_CHECK and self._side_log and self._rep_start is not None:
                # side camera: same priority as the front. Its reading stays valid for the whole curl (the
                # forearm turns in the picture plane of a side camera), so the down position AND the lift count.
                since = self._rep_start - config.HAND_WINDOW_BEFORE
                seen = [p for t, p in self._side_log if t >= since]
                s_good = sum(1 for p in seen if p == "front")
                s_bad = sum(1 for p in seen if p == "outward")
                note = f"side palm ok {s_good}/{s_good + s_bad}"
                self.last_hand_summary = f"{self.last_hand_summary}, {note}" if self.last_hand_summary else note
                if s_bad >= config.SIDE_BAD_MIN_READINGS and s_bad >= config.SIDE_BAD_RATIO * (s_good + s_bad):
                    self._reasons.add("palm_dir")
            good, bad = self._lift_palm
            if config.PALM_CHECK:
                note = f"palm ok {good}/{good + bad}"
                self.last_hand_summary = f"{self.last_hand_summary}, {note}" if self.last_hand_summary else note
                if bad >= config.PALM_BAD_MIN_READINGS and bad >= config.PALM_BAD_MAX_RATIO * (good + bad):
                    self._reasons.add("palm_dir")  # hand mostly turned the wrong way in the lower part
            if up_time is not None and up_time < config.MIN_UP_SECONDS:
                self._reasons.add("fast")
            if up_time is not None and up_time > config.MAX_UP_SECONDS:
                self._reasons.add("slow")
            # several reps in a row with the fist turned out (either camera): pause and tell the user
            self.palm_flag_last = "palm_dir" in self._reasons
            if self.palm_flag_last:
                self.palm_flags += 1
            if up_time is not None:
                self.lift_times_all.append(up_time)
            # (3 of the last 4 reps, so one rep the cameras happened to read as fine does not reset it)
            self._palm_hist = (self._palm_hist + ["palm_dir" in self._reasons])[-config.OUTWARD_WINDOW:]
            self.palm_streak = sum(self._palm_hist)
            if config.PALM_CHECK and config.OUTWARD_PAUSE and self.palm_streak >= config.OUTWARD_STREAK:
                self._palm_hist = []
                self.palm_streak = 0
                self.outward_alert = True
                self.blocked_until = max(self.blocked_until, now + config.OUTWARD_PAUSE_SECONDS)
            self.grip_flag_last = "fist" in self._reasons
            if self.grip_flag_last:
                self.grip_flags += 1
            if not config.FIST_REJECTS:
                self._reasons.discard("fist")      # grip is advice only: a bottle / dumbbell can look like an open hand
            if not config.HAND_HIDDEN_REJECTS:
                self._reasons.discard("hand_hidden")
            if not config.PALM_REJECTS and "palm_dir" in self._reasons:
                # palm direction is advice only (21 Oct: the front camera's fist-direction reading is not
                # consistent enough to fail a rep) - the rep can still count, with a tip on screen
                self._reasons.discard("palm_dir")
                self.palm_tip = True
            self.form_ok = not self._reasons
            if self.form_ok and config.MIN_DOWN_SECONDS > 0:
                self._pending = True                # good lift: counted once it has been lowered slowly
                self._top_h, self._left_top_t = wrist_h, now
            elif self.form_ok:
                event = self._count()
            else:
                self.last_reasons = [REASON_TEXT[r] for r in REASON_ORDER if r in self._reasons]
                self.reject_key = next((r for r in REASON_ORDER if r in self._reasons), None)
                for r in self._reasons:
                    self.reject_counts[r] = self.reject_counts.get(r, 0) + 1
                self.blocked_until = now + config.REJECT_PAUSE_SECONDS
                event = "rejected"

        self.last = {
            "elbow_angle": elbow, "drift": drift, "wrist_angle": wrist, "hand": hand, "palm": palm,
            "elbow_swinging": elbow_swinging, "wrist_bent": wrist_bent, "hand_open": hand_open,
            "palm_away": palm_away, "not_extended": not_extended, "not_ready": not self.ready,
            "tilt": tilt, "len_ratio": len_ratio, "foreshortened": foreshortened, "arm_tilted": arm_tilted, "arm_forward": arm_forward,
        }
        return event

    def _count(self):
        self.count += 1
        if self.last_up_time is not None:
            self.rep_times.append(self.last_up_time)
        return "counted"

    def reset(self):
        self.__init__(self.arm, self.alpha)
