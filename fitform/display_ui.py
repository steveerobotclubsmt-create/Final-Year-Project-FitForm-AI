"""All on-screen drawing lives here: joints, rep counters, stage, form status,
calories, elapsed time and the feedback bar."""

import math

import cv2

from . import config

FONT = cv2.FONT_HERSHEY_SIMPLEX
GREEN = (0, 255, 0)
RED = (0, 0, 255)
WHITE = (255, 255, 255)
YELLOW = (0, 255, 255)


def draw_arm(image, pts, counter, show_angle=False):
    color = GREEN if counter.form_ok else RED
    for joint in ("shoulder", "elbow", "wrist"):
        cv2.circle(image, tuple(pts[joint]), 10, color, -1)
    cv2.line(image, tuple(pts["shoulder"]), tuple(pts["elbow"]), WHITE, 3)
    cv2.line(image, tuple(pts["elbow"]), tuple(pts["wrist"]), WHITE, 3)
    if counter.last and show_angle:
        ex, ey = pts["elbow"]
        cv2.putText(image, f"{counter.last['elbow_angle']:.0f}", (ex + 10, ey), FONT, 0.7, (255, 255, 0), 2)



def draw_debug(image, feedback):
    """Live numbers for tuning thresholds (run with --debug)."""
    h, w = image.shape[:2]
    y = 200
    for arm in ("right", "left"):
        c = feedback.counters[arm]
        d = c.last
        if not d:
            continue
        def fmt(v):
            return "-" if v is None else f"{v:.0f}"
        txt = (f"{arm[0].upper()}: elbow {fmt(d.get('elbow_angle'))} (2D {fmt(d.get('elbow2d'))}/3D {fmt(d.get('elbow3d'))})  "
               f"drift {fmt(d.get('drift'))}  "
               f"wrist {fmt(d.get('wrist_angle'))}  palm {d.get('palm') or '-'}  stage {c.stage or '-'}")
        cv2.rectangle(image, (0, y - 20), (w, y + 6), (0, 0, 0), -1)
        cv2.putText(image, txt, (8, y), FONT, 0.55, YELLOW, 1)
        y += 28


def draw_hud(image, feedback, calories_kcal, elapsed_s, fps):
    h, w = image.shape[:2]
    for arm, x, label, label_color in (
        ("right", 0, "RIGHT", YELLOW),
        ("left", w - 180, "LEFT", (255, 100, 255)),
    ):
        counter = feedback.counters[arm]
        cv2.rectangle(image, (x, 0), (x + 180, 170), (20, 20, 20), -1)
        cv2.putText(image, label, (x + 10, 28), FONT, 0.7, label_color, 2)
        cv2.putText(image, str(counter.count), (x + 10, 95), FONT, 2.8, WHITE, 3)
        cv2.putText(image, counter.stage or "-", (x + 10, 130), FONT, 0.8, (200, 200, 200), 2)
        status, col = ("GOOD", GREEN) if counter.form_ok else ("BAD FORM", RED)
        cv2.putText(image, status, (x + 10, 158), FONT, 0.6, col, 2)
        # small hand status: fist (F) and palm direction (P), green = ok, red = wrong, grey = not seen
        if config.FIST_CHECK:
            col = {"fist": GREEN, "open": RED, "partial": RED}.get(counter.hand, (120, 120, 120))
            cv2.putText(image, "FIST", (x + 95, 118), FONT, 0.5, col, 2)
        if config.PALM_CHECK:
            col = {"front": GREEN, "inward": GREEN, "back": RED, "outward": RED}.get(counter.palm, (120, 120, 120))
            cv2.putText(image, "PALM", (x + 95, 140), FONT, 0.5, col, 2)

    mins, secs = divmod(int(elapsed_s), 60)
    cv2.putText(image, f"{calories_kcal:.2f} kcal   {mins:02d}:{secs:02d}   {fps:.0f} FPS",
                (200, 30), FONT, 0.6, WHITE, 2)

    lines = feedback.message.split("\n")
    bar = 55 if len(lines) == 1 else 80
    cv2.rectangle(image, (0, h - bar), (w, h), (20, 20, 20), -1)
    if len(lines) == 1:
        cv2.putText(image, lines[0], (10, h - 18), FONT, 0.8, feedback.message_color, 2)
    else:                                   # 'Not counted - why' + what to do
        cv2.putText(image, lines[0], (10, h - 48), FONT, 0.7, feedback.message_color, 2)
        cv2.putText(image, lines[1], (10, h - 14), FONT, 0.7, (0, 200, 255), 2)
    cv2.putText(image, "Q = quit  |  R = reset", (10, h - bar - 10), FONT, 0.45, (150, 150, 150), 1)
    return image


def draw_demo(image, t, seconds_left):
    """Start-up demo: a side-view stick figure doing a correct bicep curl, plus the key rules.
    t = seconds since the start (drives the animation)."""
    h, w = image.shape[:2]
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.82, image, 0.18, 0, image)

    # one rep every 2.6 s: lift 1.0 s, short hold at the top, lower 1.2 s, short pause at the bottom
    p = t % 2.6
    if p < 1.0:
        k = p / 1.0
    elif p < 1.2:
        k = 1.0
    elif p < 2.4:
        k = 1.0 - (p - 1.2) / 1.2
    else:
        k = 0.0
    k = 0.5 - 0.5 * math.cos(math.pi * k)          # smooth start and stop
    elbow_deg = 170 - k * 130                     # 170 (straight) -> 40 (curled)

    # figure (side view, facing right) on the left part of the screen
    cx, top = int(w * 0.27), int(h * 0.16)
    s = h / 600.0
    head = (cx, top + int(35 * s))
    shoulder = (cx, top + int(85 * s))
    hip = (cx, top + int(270 * s))
    white, green, orange = (235, 235, 235), (0, 220, 0), (0, 200, 255)
    cv2.circle(image, head, int(28 * s), white, 3)
    cv2.line(image, (cx, top + int(63 * s)), hip, white, 4)
    for dx in (-25, 25):                          # legs
        cv2.line(image, hip, (cx + int(dx * s), top + int(430 * s)), white, 4)
    shoulder = (cx + int(10 * s), shoulder[1])    # arm drawn just in front of the body line
    elbow = (shoulder[0], shoulder[1] + int(105 * s))   # upper arm stays straight down
    cv2.line(image, shoulder, elbow, green, 6)
    a = math.radians(180 - elbow_deg)             # forearm swings forward (to the right)
    wrist = (int(elbow[0] + 100 * s * math.sin(a)), int(elbow[1] + 100 * s * math.cos(a)))
    cv2.line(image, elbow, wrist, green, 6)
    cv2.circle(image, wrist, int(13 * s), orange, -1)   # fist
    cv2.circle(image, elbow, int(7 * s), white, -1)
    cv2.putText(image, "elbow stays here", (elbow[0] - int(150 * s), elbow[1] + 5), FONT, 0.5, white, 1)
    cv2.putText(image, "(side view)", (cx - int(45 * s), top + int(465 * s)), FONT, 0.5, (160, 160, 160), 1)

    x0, y = int(w * 0.46), int(h * 0.16)
    cv2.putText(image, "How to do a bicep curl", (x0, y), FONT, 0.8, orange, 2)
    rules = ["1. Face the camera, arms straight down",
             "2. Keep your upper arm still by your side",
             "3. Hold the weight in a fist,",
             "   palm facing your body",
             "4. Lift and lower steadily",
             "   (about 1 second each way)",
             "5. Straighten your arm fully at the bottom"]
    last = f"Hold your arm straight to start  ({seconds_left:.0f})"
    widest = max(cv2.getTextSize(r, FONT, 1.0, 2)[0][0] for r in rules + [last])
    fs = min(0.6, (w - x0 - 12) / widest)          # shrink the text so it always fits the window
    for i, r in enumerate(rules):
        cv2.putText(image, r, (x0, y + 45 + i * 34), FONT, fs, white, 2)
    cv2.putText(image, last, (x0, y + 45 + len(rules) * 34 + 30), FONT, fs, green, 2)
    return image
