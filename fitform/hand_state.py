"""Open-hand vs clenched-fist classification from the 21 MediaPipe Hands landmarks.
Kept free of MediaPipe imports so it can be unit-tested without a camera."""

import math

# (tip, PIP joint) for index, middle, ring and little finger
FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))


# (MCP, PIP, tip) for index, middle, ring and little finger
FINGER_JOINTS = ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20))
GRIP_BEND_MIN = 60     # degrees: a finger bent at least this much (3D) is wrapped round something
GRIP_MIN_FINGERS = 2   # this many curled / clearly bent fingers = gripping (a hand round a bottle often
                       # shows only 2 clearly bent fingers to the camera; a flat open hand shows 0-1)


def finger_bend(landmarks, mcp, pip, tip, width=1.0, height=1.0):
    """How much a finger is bent, in degrees (0 = straight), from MCP->PIP vs PIP->tip in 3D.
    Joint angles do not depend on which way the hand is turned, so this works from any camera angle."""
    def v(a, b):
        return ((landmarks[b].x - landmarks[a].x) * width, (landmarks[b].y - landmarks[a].y) * height,
                (getattr(landmarks[b], "z", 0.0) - getattr(landmarks[a], "z", 0.0)) * width)
    u, w = v(mcp, pip), v(pip, tip)
    nu, nw = math.sqrt(sum(c * c for c in u)), math.sqrt(sum(c * c for c in w))
    if nu == 0 or nw == 0:
        return 0.0
    c = max(-1.0, min(1.0, sum(a * b for a, b in zip(u, w)) / (nu * nw)))
    return math.degrees(math.acos(c))


def classify_hand(landmarks, width=1.0, height=1.0):
    """Returns 'fist', 'open' or 'partial'. 'fist' also covers a hand gripping a bottle or dumbbell handle.
    A finger counts as curled when its tip is closer to the wrist than its middle (PIP) joint is (tight fist),
    or when it is bent at least GRIP_BEND_MIN degrees (fingers wrapped round a bottle: the tips stay
    further out than the PIP joints, so the first test alone said 'not clenched')."""
    pts = [(p.x * width, p.y * height) for p in landmarks]
    wrist = pts[0]

    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    curled = 0
    for (tip, pip), (m, p, t) in zip(FINGERS, FINGER_JOINTS):
        if dist(pts[tip], wrist) < dist(pts[pip], wrist) or \
                finger_bend(landmarks, m, p, t, width, height) >= GRIP_BEND_MIN:
            curled += 1
    if curled >= GRIP_MIN_FINGERS:
        return "fist"
    if curled <= 1:
        return "open"
    return "partial"


def fist_turn_score(landmarks, arm, width=1.0, height=1.0):
    """For a clenched fist seen by the FRONT camera: < 0 = palm towards the body, > 0 = fist turned
    outward (or palm forward). From the 2D picture only (which way round the wrist / index knuckle /
    little-finger knuckle triangle appears), so MediaPipe's unreliable depth guess is not used.
    Measured 20 Oct: palm-to-body holds -0.79 to -0.91, turned-out holds +0.91 to +0.98."""
    def v(k):
        return (landmarks[k].x * width - landmarks[0].x * width,
                landmarks[k].y * height - landmarks[0].y * height,
                (getattr(landmarks[k], "z", 0.0) - getattr(landmarks[0], "z", 0.0)) * width)
    i, p = v(5), v(17)
    cx = i[1] * p[2] - i[2] * p[1]
    cy = i[2] * p[0] - i[0] * p[2]
    cz = i[0] * p[1] - i[1] * p[0]
    n = math.sqrt(cx * cx + cy * cy + cz * cz)
    if n == 0:
        return 0.0
    return (-1 if arm == "right" else 1) * cz / n


PALM_GOOD = ("front", "inward")        # standard curl: palm forward, or facing the body at the bottom
PALM_BAD = ("outward", "back")         # hand turned away from the body, or reverse grip
PALM_ALL = PALM_GOOD + PALM_BAD + ("side",)


def palm_direction(landmarks, arm, width=1.0, height=1.0, sign=1, min_score=0.35, inward_sign=1,
                   bad_min_score=None):
    """Which way the palm faces, from the 21 MediaPipe Hands landmarks of the un-mirrored image.
    The palm plane is spanned by wrist (0) -> index knuckle (5) and wrist -> little-finger knuckle (17);
    its normal (using MediaPipe's depth value z as well) gives two components:
      front  > 0: palm towards the camera      (< 0: back of the hand towards the camera)
      inward > 0: palm towards the body midline (< 0: palm turned outward, away from the body)
    Returns (label, front, inward) with label 'front' | 'inward' | 'outward' | 'back' | 'side'."""
    def v(k):
        return (landmarks[k].x * width - landmarks[0].x * width,
                landmarks[k].y * height - landmarks[0].y * height,
                (getattr(landmarks[k], "z", 0.0) - getattr(landmarks[0], "z", 0.0)) * width)
    i, p = v(5), v(17)
    n = math.sqrt(sum(c * c for c in i)) * math.sqrt(sum(c * c for c in p))
    if n == 0:
        return "side", 0.0, 0.0
    cx = i[1] * p[2] - i[2] * p[1]
    cz = i[0] * p[1] - i[1] * p[0]
    s_arm = -1 if arm == "right" else 1
    # s_arm * (i x p) is the normal out of the BACK of the hand (MediaPipe z grows away from the camera),
    # so the back normal pointing away from the camera means the palm faces the camera.
    front = s_arm * cz / n * sign
    # palm normal = -(back normal). In the un-mirrored image the person's right arm is on the image left,
    # so "towards the body" is +x for the right hand and -x for the left hand.
    inward = -s_arm * cx / n * (1 if arm == "right" else -1) * inward_sign
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
