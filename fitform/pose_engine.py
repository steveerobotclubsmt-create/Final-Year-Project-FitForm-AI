"""Wraps MediaPipe Pose: detects the 33 body landmarks in each camera frame."""

import cv2
import mediapipe as mp

from . import config

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils


class PoseEngine:
    def __init__(self):
        self.pose = mp_pose.Pose(
            model_complexity=config.MODEL_COMPLEXITY,
            min_detection_confidence=config.MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=config.MIN_TRACKING_CONFIDENCE,
        )

    def process(self, frame_bgr):
        """Runs pose detection on an un-mirrored BGR frame.
        Returns the MediaPipe pose_landmarks object, or None if no person is found."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self.pose.process(rgb)
        return results.pose_landmarks

    @staticmethod
    def draw_skeleton(image, pose_landmarks):
        """Draws the full skeleton on an image that has already been mirrored."""
        for lm in pose_landmarks.landmark:
            lm.x = 1.0 - lm.x
        mp_drawing.draw_landmarks(
            image, pose_landmarks, mp_pose.POSE_CONNECTIONS,
            mp_drawing.DrawingSpec(color=(100, 100, 100), thickness=1, circle_radius=1),
            mp_drawing.DrawingSpec(color=(100, 100, 100), thickness=1),
        )
        for lm in pose_landmarks.landmark:
            lm.x = 1.0 - lm.x

    def close(self):
        self.pose.close()
