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
