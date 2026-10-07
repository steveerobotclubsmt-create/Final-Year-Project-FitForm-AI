"""Runs MediaPipe Hands and reports, for each arm, whether that hand is a fist or open.
Hands are matched to arms by distance to the wrist point found by MediaPipe Pose."""

import math

import cv2

from . import config
from .hand_state import classify_hand

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
        if pose_landmarks is not None and self.hand_landmarks:
            lm = pose_landmarks.landmark
            for arm, wi in POSE_WRIST.items():
                if lm[wi].visibility < 0.5:
                    continue
                wx, wy = lm[wi].x * w, lm[wi].y * h
                best, best_d = None, float("inf")
                for hand in self.hand_landmarks:
                    d = math.hypot(hand.landmark[0].x * w - wx, hand.landmark[0].y * h - wy)
                    if d < best_d:
                        best, best_d = hand, d
                if best is not None and best_d < config.HAND_MATCH_DIST * w:
                    states[arm] = classify_hand(best.landmark, w, h)
        self.states = states
        return states

    def close(self):
        self.hands.close()
