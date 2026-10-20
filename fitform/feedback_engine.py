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
        self._msg_time = -1e9

    def update(self, landmarks, width, height, now, world=None, hands=None, hand_points=None, palms=None):
        """landmarks: MediaPipe pose_landmarks for this frame (None if nobody detected).
        world: MediaPipe pose_world_landmarks (3D) or None. hands: {'right': state, 'left': state} or None.
        hand_points: {'right': (wrist_px, knuckle_px), ...} from MediaPipe Hands (un-mirrored pixels) or None.
        Returns (events, drawn): events = [(arm, 'counted'|'rejected')], drawn = {arm: points}."""
        events, drawn = [], {}
        hands = hands or {}
        hand_points = hand_points or {}
        palms = palms or {}
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
                meas2d = measure_from_points(pts)
                meas3d = measure_from_world(world.landmark, arm) if world is not None else None
                meas = meas3d if (meas3d is not None and config.USE_3D_ANGLES) else meas2d
                meas = dict(meas)
                # sizes in the picture for the elbow forward/back check (shoulder width = scale)
                lm = landmarks.landmark
                sw = ((lm[11].x - lm[12].x) * width) ** 2 + ((lm[11].y - lm[12].y) * height) ** 2
                meas["shoulder_w"] = sw ** 0.5
                # standing sideways: the shoulders overlap in the picture, so shoulder width is no use as a
                # scale; the elbow moving forward/back then shows directly as the upper arm tilting instead
                tx = ((lm[11].x + lm[12].x) - (lm[23].x + lm[24].x)) / 2 * width
                ty = ((lm[11].y + lm[12].y) - (lm[23].y + lm[24].y)) / 2 * height
                torso = (tx * tx + ty * ty) ** 0.5
                meas["side_view"] = torso > 0 and meas["shoulder_w"] / torso < config.SIDE_VIEW_RATIO
                sx, sy = pts["shoulder"]
                ex, ey = pts["elbow"]
                meas["upper_len"] = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
                meas["upper_vec2d"] = [ex - sx, ey - sy]
                # Wrist straightness: forearm vs the middle knuckle from MediaPipe Hands. The pose model's
                # "index" point folds into the palm when you make a fist, so it is not used for this.
                hp = hand_points.get(arm)
                if hp is not None:
                    lm = landmarks.landmark
                    e = ARMS[arm]["elbow"]
                    meas["wrist"] = get_angle((lm[e].x * width, lm[e].y * height), hp[0], hp[1])
                else:
                    meas["wrist"] = None
                event = self.counters[arm].update(meas, now, hands.get(arm), palms.get(arm))
                # both angle versions, so --debug can show which one matches the real arm
                self.counters[arm].last["elbow2d"] = meas2d["elbow"]
                self.counters[arm].last["elbow3d"] = meas3d["elbow"] if meas3d is not None else None
                if event:
                    events.append((arm, event))
                drawn[arm] = pts
        old = (self.message, self.message_color)
        self._set_message(list(drawn), partly_visible, events)
        new = (self.message, self.message_color)
        # keep a message on screen for a moment so it does not flicker; rep results always show at once
        if new != old:
            if events or now - self._msg_time >= config.MESSAGE_HOLD_SECONDS:
                self._msg_time = now
            else:
                self.message, self.message_color = old
        return events, drawn

    def _set_message(self, seen_arms, partly_visible=False, events=()):
        if not seen_arms:
            if partly_visible:
                self.message, self.message_color = "Step back - keep your hands in view", ORANGE
            else:
                self.message, self.message_color = "Show your full arm to the camera", GREY
            return
        # A rep that just finished: say whether it counted (and why not).
        for arm, event in events:
            c = self.counters[arm]
            if event == "counted":
                self.message, self.message_color = f"{arm.upper()}: Good rep!", GREEN
            else:
                why = c.last_reasons[0] if c.last_reasons else "check your form"
                self.message, self.message_color = f"{arm.upper()}: Not counted - {why}", RED
            return
        # Otherwise the most urgent live problem on any visible arm. An arm that has not started (for
        # example holding the phone) is ignored while the other arm is exercising.
        active = [a for a in seen_arms if self.counters[a].ready]
        if active:
            seen_arms = active
        for check, text, color in (
            ("not_ready", "Hold your arm straight to start", ORANGE),
            ("arm_tilted", "Keep your upper arm pointing down", RED),
            ("arm_forward", "Keep your elbow by your side", RED),
            ("elbow_swinging", "Keep your elbow still", RED),
            ("hand_open", "Clench your fist", RED),
            ("palm_away", "Don't turn your hand outward", RED),
            ("wrist_bent", "Keep your wrist straight", RED),
            ("not_extended", "Lower your arm fully", ORANGE),
        ):
            for arm in seen_arms:
                if self.counters[arm].last.get(check):
                    self.message, self.message_color = f"{arm.upper()}: {text}", color
                    return
        self.message, self.message_color = "Good form", GREEN

    def overall_form_ok(self):
        return all(c.form_ok for c in self.counters.values())

    def total_reps(self):
        return sum(c.count for c in self.counters.values())

    def reset(self):
        for c in self.counters.values():
            c.reset()
        self.message, self.message_color = "Reset!", GREY
