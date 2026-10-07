"""All on-screen drawing lives here: joints, rep counters, stage, form status,
calories, elapsed time and the feedback bar."""

import cv2

FONT = cv2.FONT_HERSHEY_SIMPLEX
GREEN = (0, 255, 0)
RED = (0, 0, 255)
WHITE = (255, 255, 255)
YELLOW = (0, 255, 255)


def draw_arm(image, pts, counter):
    color = GREEN if counter.form_ok else RED
    for joint in ("shoulder", "elbow", "wrist"):
        cv2.circle(image, tuple(pts[joint]), 10, color, -1)
    cv2.line(image, tuple(pts["shoulder"]), tuple(pts["elbow"]), WHITE, 3)
    cv2.line(image, tuple(pts["elbow"]), tuple(pts["wrist"]), WHITE, 3)
    if counter.last:
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
        txt = (f"{arm[0].upper()}: elbow {fmt(d.get('elbow_angle'))}  drift {fmt(d.get('drift'))}  "
               f"wrist {fmt(d.get('wrist_angle'))}  hand {d.get('hand') or '-'}  stage {c.stage or '-'}")
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
        hand = {"fist": ("FIST", GREEN), "open": ("OPEN", RED), "partial": ("HAND?", YELLOW)}.get(counter.hand)
        if hand:
            cv2.putText(image, hand[0], (x + 105, 130), FONT, 0.6, hand[1], 2)

    mins, secs = divmod(int(elapsed_s), 60)
    cv2.putText(image, f"{calories_kcal:.2f} kcal   {mins:02d}:{secs:02d}   {fps:.0f} FPS",
                (200, 30), FONT, 0.6, WHITE, 2)

    cv2.rectangle(image, (0, h - 55), (w, h), (20, 20, 20), -1)
    cv2.putText(image, feedback.message, (10, h - 18), FONT, 0.8, feedback.message_color, 2)
    cv2.putText(image, "Q = quit  |  R = reset", (10, h - 65), FONT, 0.45, (150, 150, 150), 1)
    return image
