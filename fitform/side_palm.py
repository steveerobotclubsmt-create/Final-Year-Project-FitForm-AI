"""Second camera at the user's side, used only to judge the palm direction of the near arm.

Why a side camera: from the front, a clenched fist turned outward looks almost the same as one facing
the body. The front calibration (20 Oct) showed that the 2D 'which side of the hand faces the camera'
reading splits the positions into {towards body, backward} vs {forward, outward}. Seen from 90 degrees to
the side, the same reading splits them into {towards body, forward} (correct) vs {outward, backward}
(wrong) - exactly the rule we need. It uses only the 2D picture, not MediaPipe's unreliable depth."""

import math
import time

import cv2

from . import config
from .hand_state import classify_hand, palm_direction


class SidePalmChecker:
    def __init__(self, stream, arm="right", rotate=0, every_n=None):
        import mediapipe as mp   # imported here so the rest can be tested without it
        self.hands = mp.solutions.hands.Hands(
            max_num_hands=2, model_complexity=config.HAND_MODEL_COMPLEXITY,
            min_detection_confidence=config.HAND_MIN_CONFIDENCE,
            min_tracking_confidence=config.HAND_MIN_CONFIDENCE)
        self.stream = stream
        self.arm = arm
        self.rotate_code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                            270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(rotate)
        self.every_n = max(1, every_n or config.SIDE_EVERY_N)
        self._n = 0
        self._last_id = -1
        self.label = None        # 'front' (correct: forward or towards the body) | 'outward' (wrong) | 'side'
        self.score = None        # > 0 correct, < 0 wrong
        self.state = None        # 'fist' (clenched or gripping a bottle) | 'open' | 'partial' | None (not seen)
        self.frame = None        # last side picture with the hand drawn, for the small preview
        self.seen_at = 0.0

    def process(self):
        """Run once per main frame (in the worker thread). Returns the palm label for self.arm."""
        self._n += 1
        if self._n % self.every_n:
            return self.label
        fid, frame = self.stream.read()
        if frame is None or fid == self._last_id:
            return self.label
        self._last_id = fid
        if self.rotate_code is not None:
            frame = cv2.rotate(frame, self.rotate_code)
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        res = self.hands.process(rgb)
        hands = res.multi_hand_landmarks or []
        if hands:
            # MediaPipe's own left/right guess; it assumes a mirrored picture, so in the camera's own
            # (un-mirrored) picture the person's RIGHT hand is labelled "Left"
            want = "Left" if self.arm == "right" else "Right"
            labels = []
            for k in range(len(hands)):
                try:
                    cl = res.multi_handedness[k].classification[0]
                    labels.append((cl.label, cl.score))
                except (IndexError, TypeError, AttributeError):
                    labels.append((None, 0.0))

            def area(hl):
                xs = [p.x for p in hl.landmark]
                ys = [p.y for p in hl.landmark]
                return (max(xs) - min(xs)) * (max(ys) - min(ys))
            # the arm next to the camera: its hand is the bigger one and should carry the right label;
            # a lone hand confidently labelled as the OTHER hand is the far arm, so it is not used
            cands = [(area(hl) * (2.0 if lab == want else 1.0), k) for k, (hl, (lab, sc)) in
                     enumerate(zip(hands, labels)) if not (len(hands) == 1 and lab not in (None, want) and sc > 0.8)]
            hands = [hands[max(cands)[1]]] if cands else []
        if hands:
            b = hands[0].landmark
            self.state = classify_hand(b, w, h)
            front = palm_direction(b, self.arm, w, h)[1]
            self.score = config.SIDE_PALM_SIGN * front
            if self.score > config.SIDE_PALM_MIN:
                self.label = "front"
            elif self.score < -config.SIDE_PALM_MIN:
                self.label = "outward"
            else:
                self.label = "side"
            self.seen_at = time.time()
            for p in b:
                cv2.circle(frame, (int(p.x * w), int(p.y * h)), 3, (0, 255, 255), -1)
        elif time.time() - self.seen_at > 0.5:
            self.label, self.score = "side", None   # hand not seen by the side camera: do not judge
            self.state = None                        # (the front camera's fist reading is used instead)
        self.frame = frame
        return self.label

    def draw_preview(self, image):
        """Small picture of the side camera in the bottom-right corner, framed green/red/grey."""
        if self.frame is None:
            return
        ih, iw = image.shape[:2]
        pw = iw // 4
        ph = int(pw * self.frame.shape[0] / self.frame.shape[1])
        small = cv2.resize(self.frame, (pw, ph))
        x, y = iw - pw - 8, ih - ph - 60
        image[y:y + ph, x:x + pw] = small
        col = {"front": (0, 255, 0), "outward": (0, 0, 255)}.get(self.label, (160, 160, 160))
        cv2.rectangle(image, (x, y), (x + pw, y + ph), col, 3)
        txt = "SIDE: palm ok" if self.label == "front" else ("SIDE: turned out" if self.label == "outward"
                                                              else "SIDE: unclear")
        if self.state:
            txt += " | fist" if self.state == "fist" else " | not clenched"
        cv2.putText(image, txt, (x + 4, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)

    def close(self):
        self.hands.close()
