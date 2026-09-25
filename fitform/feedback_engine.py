"""Runs the rep counters on the pose seen by the camera and decides what
feedback to show."""

from .bicep_curl import ARMS, BicepCurlCounter, arm_points, measure_from_points

RED = (0, 0, 255)
ORANGE = (0, 165, 255)
GREEN = (0, 255, 0)
GREY = (200, 200, 200)


class FeedbackEngine:
    def __init__(self):
        self.counters = {arm: BicepCurlCounter(arm) for arm in ARMS}
        self.message = "Show your full arm to the camera"
        self.message_color = GREY

    def update(self, landmarks, width, height, now):
        """landmarks: MediaPipe pose_landmarks for this frame (None if nobody detected).
        Returns (events, drawn): events = [(arm, 'counted'|'rejected')],
        drawn = {arm: points} for drawing joints."""
        events, drawn = [], {}
        if landmarks is not None:
            for arm in ARMS:
                pts = arm_points(landmarks.landmark, arm, width, height)
                if pts is None:
                    continue
                event = self.counters[arm].update(measure_from_points(pts), now)
                if event:
                    events.append((arm, event))
                drawn[arm] = pts
        self._set_message(list(drawn))
        return events, drawn

    def _set_message(self, seen_arms):
        if not seen_arms:
            self.message, self.message_color = "Show your full arm to the camera", GREY
            return
        # Report the most urgent problem on any visible arm.
        for check, text, color in (
            ("elbow_swinging", "Keep elbow still!", RED),
            ("wrist_bent", "Straighten your wrist!", RED),
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
