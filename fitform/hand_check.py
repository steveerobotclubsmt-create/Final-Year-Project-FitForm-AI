"""Runs MediaPipe Hands and reports, for each arm, whether that hand is a fist or open.
Hands are matched to arms by distance to the wrist point found by MediaPipe Pose."""

import math

import cv2

from . import config
from .hand_state import classify_hand, palm_direction

POSE_WRIST = {"right": 16, "left": 15}


class HandChecker:
    def __init__(self, every_n=config.HAND_EVERY_N):
        import mediapipe as mp   # imported here so the rest of the project can be tested without it
        self._mp_hands = mp.solutions.hands
        self.hands = self._mp_hands.Hands(
            max_num_hands=2,
            model_complexity=config.HAND_MODEL_COMPLEXITY,
            min_detection_confidence=config.HAND_MIN_CONFIDENCE,
            min_tracking_confidence=config.HAND_MIN_CONFIDENCE,
        )
        self.every_n = max(1, every_n)
        self._frame = 0
        self.states = {"right": None, "left": None}
        self.points = {"right": None, "left": None}   # (wrist, middle knuckle) pixel points, un-mirrored
        self.palms = {"right": None, "left": None}    # 'front' | 'back' | 'side' | None
        self.palm_scores = {"right": None, "left": None}   # -1..1, >0 = palm towards the camera
        self.hand_landmarks = []

    def process(self, frame_bgr, pose_landmarks):
        """frame_bgr: the same un-mirrored frame given to PoseEngine.
        Returns {'right': 'fist'|'open'|'partial'|None, 'left': ...}. None = hand not seen."""
        self._frame += 1
        if self._frame % self.every_n:
            return self.states                      # reuse the last result on skipped frames
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self.hands.process(rgb)
        self.hand_landmarks = result.multi_hand_landmarks or []
        states = {"right": None, "left": None}
        points = {"right": None, "left": None}
        palms = {"right": None, "left": None}
        scores = {"right": None, "left": None}
        if pose_landmarks is not None and self.hand_landmarks:
            lm = pose_landmarks.landmark
            # every (arm, hand) pair with its distance; then give each arm its nearest hand, one hand per arm
            pairs = []
            for arm, wi in POSE_WRIST.items():
                if lm[wi].visibility < 0.5:
                    continue
                wx, wy = lm[wi].x * w, lm[wi].y * h
                for k, hand in enumerate(self.hand_landmarks):
                    d = math.hypot(hand.landmark[0].x * w - wx, hand.landmark[0].y * h - wy)
                    if d < config.HAND_MATCH_DIST * w:
                        pairs.append((d, arm, k))
            used_arms, used_hands = set(), set()
            for d, arm, k in sorted(pairs):
                if arm in used_arms or k in used_hands:
                    continue
                used_arms.add(arm)
                used_hands.add(k)
                b = self.hand_landmarks[k].landmark
                states[arm] = classify_hand(b, w, h)
                points[arm] = ((b[0].x * w, b[0].y * h), (b[9].x * w, b[9].y * h))
                palms[arm], scores[arm] = palm_direction(b, arm, w, h, config.PALM_SIGN, config.PALM_MIN_SCORE)
        self.states = states
        self.points = points
        self.palms = palms
        self.palm_scores = scores
        return states

    def close(self):
        self.hands.close()
