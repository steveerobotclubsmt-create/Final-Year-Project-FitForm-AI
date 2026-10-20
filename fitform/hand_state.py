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


PALM_GOOD = ("front", "inward")        # standard curl: palm forward, or facing the body at the bottom
PALM_BAD = ("outward", "back")         # hand turned away from the body, or reverse grip
PALM_ALL = PALM_GOOD + PALM_BAD + ("side",)


def palm_direction(landmarks, arm, width=1.0, height=1.0, sign=1, min_score=0.35, inward_sign=1,
                   bad_min_score=None, toward_mid=None):
    """Which way the palm faces, from the 21 MediaPipe Hands landmarks of the un-mirrored image.
    The palm plane is spanned by wrist (0) -> index knuckle (5) and wrist -> little-finger knuckle (17);
    its normal (using MediaPipe's depth value z as well) gives two components:
      front  > 0: palm towards the camera      (< 0: back of the hand towards the camera)
      inward > 0: palm towards the body midline (< 0: palm turned outward, away from the body)
    toward_mid: optional (x, z) direction from this arm's shoulder to the other shoulder (camera axes). With it,
    'front' and 'inward' are measured against the body instead of the camera, so they stay right when the
    person stands sideways. Without it the person is assumed to face the camera.
    Returns (label, front, inward) with label 'front' | 'inward' | 'outward' | 'back' | 'side'."""
    def v(k):
        return (landmarks[k].x * width - landmarks[0].x * width,
                landmarks[k].y * height - landmarks[0].y * height,
                (getattr(landmarks[k], "z", 0.0) - getattr(landmarks[0], "z", 0.0)) * width)
    i, p = v(5), v(17)
    cx = i[1] * p[2] - i[2] * p[1]
    cy = i[2] * p[0] - i[0] * p[2]
    cz = i[0] * p[1] - i[1] * p[0]
    # unit normal of the palm plane: its direction does not depend on how far apart the knuckles look,
    # so a fist seen edge-on still gives a clear reading (the old |i||p| scaling made those look 'unclear')
    n = math.sqrt(cx * cx + cy * cy + cz * cz)
    if n == 0:
        return "side", 0.0, 0.0
    s_arm = -1 if arm == "right" else 1
    # s_arm * (i x p) is the normal out of the BACK of the hand (MediaPipe z grows away from the camera);
    # the palm normal is the opposite.
    px, pz = -s_arm * cx / n, -s_arm * cz / n
    if toward_mid is None:
        # facing the camera: in the un-mirrored image the right arm is on the image left, so "towards the
        # body" is +x for the right hand and -x for the left hand; "front" = towards the camera (-z)
        toward_mid = (1.0, 0.0) if arm == "right" else (-1.0, 0.0)
    lx, lz = toward_mid
    ln = math.hypot(lx, lz) or 1.0
    lx, lz = lx / ln, lz / ln
    s_side = 1 if arm == "right" else -1
    fx, fz = s_side * lz, -s_side * lx           # the way the person faces (perpendicular to the shoulders)
    front = (px * fx + pz * fz) * sign
    inward = (px * lx + pz * lz) * inward_sign
    if max(abs(front), abs(inward)) < min_score:
        return "side", front, inward
    if abs(front) >= abs(inward):
        label, score = ("front" if front > 0 else "back"), abs(front)
    else:
        label, score = ("inward" if inward > 0 else "outward"), abs(inward)
    # a wrong direction must be clear before it counts against the rep; weak ones are 'side' (unclear)
    if label in PALM_BAD and bad_min_score is not None and score < bad_min_score:
        return "side", front, inward
    return label, front, inward
