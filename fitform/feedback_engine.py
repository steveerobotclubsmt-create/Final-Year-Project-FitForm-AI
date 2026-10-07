"""Runs the rep counters on the pose seen by the camera and decides what
feedback to show."""

from . import config
from .bicep_curl import ARMS, BicepCurlCounter, arm_points, get_angle, measure_from_points, measure_from_world

RED = (0, 0, 255)
ORANGE = (0, 165, 255)
GREEN = (0, 255, 0)
GREY = (200, 200, 200)


class FeedbackEngine:
    def __init__(self):
        self.counters = {arm: BicepCurlCounter(arm) for arm in ARMS}
        self.message = "Show your full arm to the camera"
        self.message_color = GREY

    def update(self, landmarks, width, height, now, world=None, hands=None, hand_points=None):
        """landmarks: MediaPipe pose_landmarks for this frame (None if nobody detected).
        world: MediaPipe pose_world_landmarks (3D) or None. hands: {'right': state, 'left': state} or None.
        hand_points: {'right': (wrist_px, knuckle_px), ...} from MediaPipe Hands (un-mirrored pixels) or None.
        Returns (events, drawn): events = [(arm, 'counted'|'rejected')], drawn = {arm: points}."""
        events, drawn = [], {}
        hands = hands or {}
        hand_points = hand_points or {}
        partly_visible = False
        if landmarks is not None:
            for arm in ARMS:
                pts = arm_points(landmarks.landmark, arm, width, height)
                if pts is None:
                    idx = ARMS[arm]
                    lm = landmarks.landmark
                    if min(lm[idx["shoulder"]].visibility, lm[idx["elbow"]].visibility) > config.LANDMARK_VISIBILITY_MIN:
                        partly_visible = True     # arm seen but the hand/wrist is out of view
                    continue
                if world is not None and config.USE_3D_ANGLES:
                    meas = measure_from_world(world.landmark, arm)
                else:
                    meas = measure_from_points(pts)
                # Wrist straightness: forearm vs the middle knuckle from MediaPipe Hands. The pose model's
                # "index" point folds into the palm when you make a fist, so it is not used for this.
                hp = hand_points.get(arm)
                if hp is not None:
                    lm = landmarks.landmark
                    e = ARMS[arm]["elbow"]
                    meas["wrist"] = get_angle((lm[e].x * width, lm[e].y * height), hp[0], hp[1])
                else:
                    meas["wrist"] = None
                event = self.counters[arm].update(meas, now, hands.get(arm))
                if event:
                    events.append((arm, event))
                drawn[arm] = pts
        self._set_message(list(drawn), partly_visible)
        return events, drawn

    def _set_message(self, seen_arms, partly_visible=False):
        if not seen_arms:
            if partly_visible:
                self.message, self.message_color = "Step back - keep your hands in view", ORANGE
            else:
                self.message, self.message_color = "Show your full arm to the camera", GREY
            return
        # Report the most urgent problem on any visible arm.
        for check, text, color in (
            ("elbow_swinging", "Keep elbow still!", RED),
            ("wrist_bent", "Straighten your wrist!", RED),
            ("palm_open", "Clench your fist!", RED),
            ("not_extended", "Extend arm fully!", ORANGE),
        ):
            for arm in seen_arms:
                if self.counters[arm].last.get(check):
                    self.message, self.message_color = f"{arm.upper()}: {text}", color
                    return
        arm = seen_arms[0]
        c = self.counters[arm]
        if c.stage == "up" and not c.form_ok:
            self.message, self.message_color = f"{arm.upper()}: Fix form - won't count!", RED
        elif c.stage == "up":
            self.message, self.message_color = f"{arm.upper()}: Good curl!", GREEN
        else:
            self.message, self.message_color = "Good form!", GREEN

    def overall_form_ok(self):
        return all(c.form_ok for c in self.counters.values())

    def total_reps(self):
        return sum(c.count for c in self.counters.values())

    def reset(self):
        for c in self.counters.values():
            c.reset()
        self.message, self.message_color = "Reset!", GREY
