"""Open-hand vs clenched-fist classification from the 21 MediaPipe Hands landmarks.
Kept free of MediaPipe imports so it can be unit-tested without a camera."""

import math

# (tip, PIP joint) for index, middle, ring and little finger
FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))


def classify_hand(landmarks, width=1.0, height=1.0):
    """Returns 'fist', 'open' or 'partial'.
    A finger counts as curled when its tip is closer to the wrist than its middle (PIP) joint is."""
    pts = [(p.x * width, p.y * height) for p in landmarks]
    wrist = pts[0]

    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    curled = sum(1 for tip, pip in FINGERS if dist(pts[tip], wrist) < dist(pts[pip], wrist))
    if curled >= 3:
        return "fist"
    if curled <= 1:
        return "open"
    return "partial"


def palm_direction(landmarks, arm, width=1.0, height=1.0, sign=1, min_score=0.3):
    """Which way the palm faces the camera, from the un-mirrored image.
    Uses the triangle wrist (0) - index knuckle (5) - little-finger knuckle (17): it flips its
    orientation when the hand turns from palm-to-camera to back-of-hand-to-camera, whatever the
    hand's rotation in the picture. Returns ('front' | 'back' | 'side', score -1..1)."""
    w = (landmarks[0].x * width, landmarks[0].y * height)
    i = (landmarks[5].x * width - w[0], landmarks[5].y * height - w[1])
    p = (landmarks[17].x * width - w[0], landmarks[17].y * height - w[1])
    n = math.hypot(*i) * math.hypot(*p)
    if n == 0:
        return "side", 0.0
    cross = (i[0] * p[1] - i[1] * p[0]) / n          # sin of the angle between the two knuckle lines
    score = (-cross if arm == "right" else cross) * sign   # >0: palm faces the camera
    if score > min_score:
        return "front", score
    if score < -min_score:
        return "back", score
    return "side", score
