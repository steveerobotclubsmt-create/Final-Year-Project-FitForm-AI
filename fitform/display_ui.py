"""All on-screen drawing lives here: joints, rep counters, stage, form status,
calories, elapsed time and the feedback bar."""

import math

import cv2
import numpy as np

from . import config

FONT = cv2.FONT_HERSHEY_SIMPLEX
GREEN = (0, 255, 0)
RED = (0, 0, 255)
WHITE = (255, 255, 255)
YELLOW = (0, 255, 255)


class ArmSmoother:
    """Steadies the drawn shoulder / elbow / wrist points with a One-Euro filter (Casiez et al., CHI 2012): strong
    smoothing while a point is nearly still, where the pose model's frame-to-frame wobble shows as jitter, and
    little while it moves fast, so the drawing does not lag behind the arm. Only the drawing uses it - the rep
    counter keeps its own smoothing of the measured angles."""

    def __init__(self, min_cutoff=None, beta=None, reset_after=0.5):
        self.min_cutoff = config.DRAW_SMOOTH_MIN_CUTOFF if min_cutoff is None else min_cutoff   # Hz, when still
        self.beta = config.DRAW_SMOOTH_BETA if beta is None else beta     # how fast the cut-off rises with speed
        self.d_cutoff = 1.0                                               # Hz, for the speed estimate
        self.reset_after = reset_after        # arm not drawn this long: start again (no slide from an old spot)
        self._state = {}                      # (arm, joint) -> (time, position, speed)

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def update(self, drawn, now):
        """drawn: {arm: {joint: [x, y]}} for this frame -> the same with smoothed integer points."""
        out = {}
        for arm, pts in drawn.items():
            sm = {}
            for joint, p in pts.items():
                p = np.array(p, float)
                key = (arm, joint)
                st = self._state.get(key)
                if st is None or now - st[0] > self.reset_after or now <= st[0]:
                    self._state[key] = (now, p, np.zeros(2))
                    sm[joint] = [int(round(p[0])), int(round(p[1]))]
                    continue
                t0, x0, v0 = st
                dt = now - t0
                v = v0 + self._alpha(self.d_cutoff, dt) * ((p - x0) / dt - v0)
                cutoff = self.min_cutoff + self.beta * float(np.linalg.norm(v))
                x = x0 + self._alpha(cutoff, dt) * (p - x0)
                self._state[key] = (now, x, v)
                sm[joint] = [int(round(x[0])), int(round(x[1]))]
            out[arm] = sm
        return out


def draw_arm(image, pts, counter, show_angle=False):
    color = GREEN if counter.form_ok else RED
    for joint in ("shoulder", "elbow", "wrist"):
        cv2.circle(image, tuple(pts[joint]), 10, color, -1)
    cv2.line(image, tuple(pts["shoulder"]), tuple(pts["elbow"]), WHITE, 3)
    cv2.line(image, tuple(pts["elbow"]), tuple(pts["wrist"]), WHITE, 3)
    if show_angle and counter.last.get("elbow_angle") is not None:
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
    # the picture is mirrored, so the person's right arm is on the right of the screen: its board goes there too
    for arm, x, label, label_color in (
        ("right", w - 180, "RIGHT", YELLOW),
        ("left", 0, "LEFT", (255, 100, 255)),
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
             "3. Hold the weight in a fist, facing your",
             "   body (parallel to it) - not turned out",
             "4. Lift and lower steadily",
             "   (about 1 second each way)",
             "5. Straighten your arm fully at the bottom"]
    last = f"Get ready - starting in {max(1, int(seconds_left))}"
    widest = max(cv2.getTextSize(r, FONT, 1.0, 2)[0][0] for r in rules + [last])
    fs = min(0.6, (w - x0 - 12) / widest)          # shrink the text so it always fits the window
    for i, r in enumerate(rules):
        cv2.putText(image, r, (x0, y + 45 + i * 34), FONT, fs, white, 2)
    cv2.putText(image, last, (x0, y + 45 + len(rules) * 34 + 30), FONT, fs, green, 2)
    return image


def draw_saved(image, summary, url, goal=None):
    """After a session: totals, the next goal and where to see everything."""
    h, w = image.shape[:2]
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.85, image, 0.15, 0, image)
    green, white, orange = (0, 220, 0), (235, 235, 235), (0, 200, 255)
    who = summary.get("user", "guest")
    lines = [("Session saved!" if who == "guest" else f"Session saved to {who}'s account!", 1.0, green),
             (f"Reps: right {summary['reps_right']}  left {summary['reps_left']}", 0.75, white),
             (f"Calories: {summary['calories_kcal']:.1f} kcal   Time: {int(summary['duration_s'] // 60)}:"
              f"{int(summary['duration_s'] % 60):02d}", 0.75, white)]
    if goal:
        lines.append((f"Next goal: {goal['sets']} x {goal['reps']} reps per arm (~{goal['kcal']} kcal)", 0.7, orange))
    lines += [("Details on your phone:", 0.65, white), (url, 0.8, orange)]
    y = int(h * 0.28)
    for text, fs, col in lines:
        (tw, th), _ = cv2.getTextSize(text, FONT, fs, 2)
        fs2 = min(fs, fs * (w - 30) / max(tw, 1))
        (tw, th), _ = cv2.getTextSize(text, FONT, fs2, 2)
        cv2.putText(image, text, ((w - tw) // 2, y), FONT, fs2, col, 2)
        y += int(th * 2.2)
    return image


def draw_idle(image, url="", qr=None, user=None, login_required=False):
    """No session running: QR code to log in on the phone, or a greeting when someone is logged in."""
    h, w = image.shape[:2]
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.75, image, 0.25, 0, image)
    orange, white, green = (0, 200, 255), (235, 235, 235), (0, 220, 0)
    if user:
        lines = [(f"Hi {user}!", 1.1, green), ("Stand in front of the camera and start curling", 0.7, white)]
        y = int(h * 0.45)
    else:
        lines = [("FitForm AI", 1.1, orange), ("Scan to log in on your phone", 0.7, white), (url, 0.6, white),
                 ("then tap 'Train on this device'" if login_required else "(or just start curling as a guest)",
                  0.55, (160, 160, 160))]
        y = int(h * 0.12)
        if qr is not None:
            size = int(min(h, w) * 0.42)
            big = cv2.resize(qr, (size, size), interpolation=cv2.INTER_NEAREST)
            big = cv2.copyMakeBorder(big, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
            big = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
            x0, y0 = (w - big.shape[1]) // 2, int(h * 0.42)
            image[y0:y0 + big.shape[0], x0:x0 + big.shape[1]] = big
    for text, fs, col in lines:
        (tw, th), _ = cv2.getTextSize(text, FONT, fs, 2)
        cv2.putText(image, text, ((w - tw) // 2, y), FONT, fs, col, 2)
        y += int(th * 2.2)
    return image


def draw_position(image, result, progress=0.0):
    """Position check before the first rep: what to do, a checklist, and a bar while a good position is held."""
    h, w = image.shape[:2]
    x0, y0, pw = int(w * 0.18), int(h * 0.22), int(w * 0.64)
    rows = len(result["items"]) if result else 0
    ph = 120 + 30 * rows
    overlay = image.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + pw, y0 + ph), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.8, image, 0.2, 0, image)
    orange, green, white, red = (0, 200, 255), (0, 220, 0), (235, 235, 235), (60, 60, 230)
    cv2.putText(image, "Position check", (x0 + 14, y0 + 30), FONT, 0.7, white, 2)
    if result is None:
        text, col = "Stand in front of the camera", orange
    elif result["problem"]:
        text, col = result["advice"], orange
    else:
        text, col = "Good - hold still...", green
    (tw, _), _ = cv2.getTextSize(text, FONT, 0.75, 2)
    fs = min(0.75, 0.75 * (pw - 28) / max(tw, 1))               # always fits the panel
    cv2.putText(image, text, (x0 + 14, y0 + 66), FONT, fs, col, 2)
    if result and not result["problem"]:
        cv2.rectangle(image, (x0 + 14, y0 + 80), (x0 + pw - 14, y0 + 92), (70, 70, 70), -1)
        cv2.rectangle(image, (x0 + 14, y0 + 80), (x0 + 14 + int((pw - 28) * progress), y0 + 92), green, -1)
    for i, (label, ok) in enumerate(result["items"] if result else []):
        y = y0 + 122 + 30 * i
        cv2.circle(image, (x0 + 26, y - 6), 8, green if ok else red, -1)
        cv2.putText(image, label, (x0 + 44, y), FONT, 0.6, white if ok else (170, 170, 170), 1)
    return image


def draw_workout_line(image, text):
    """'Set 2 of 3   Right 5/8   Left 8/8' (or the challenge's best) under the time line, between the boards."""
    h, w = image.shape[:2]
    room = w - 2 * 185
    (tw, th), _ = cv2.getTextSize(text, FONT, 0.65, 2)
    fs = min(0.65, 0.65 * room / max(tw, 1))
    (tw, th), _ = cv2.getTextSize(text, FONT, fs, 2)
    x = (w - tw) // 2
    cv2.rectangle(image, (x - 8, 42), (x + tw + 8, 50 + th + 8), (20, 20, 20), -1)
    cv2.putText(image, text, (x, 50 + th), FONT, fs, (0, 220, 255), 2)
    return image


def draw_rest(image, seconds_left, next_set, sets):
    """Rest between sets: a big countdown in the middle (the session stays open, even out of view)."""
    h, w = image.shape[:2]
    overlay = image.copy()
    cv2.rectangle(overlay, (w // 2 - 230, h // 2 - 120), (w // 2 + 230, h // 2 + 110), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.85, image, 0.15, 0, image)
    m, s = divmod(int(seconds_left + 0.999), 60)
    for text, fs, col, y in (("REST", 1.0, (0, 220, 0), h // 2 - 70),
                             (f"{m}:{s:02d}", 2.6, (255, 255, 255), h // 2 + 20),
                             (f"Set {next_set} of {sets} next - or curl to start now", 0.6, (0, 200, 255), h // 2 + 75)):
        (tw, th), _ = cv2.getTextSize(text, FONT, fs, 3 if fs > 2 else 2)
        cv2.putText(image, text, ((w - tw) // 2, y), FONT, fs, col, 3 if fs > 2 else 2)
    return image


def draw_banner(image, text, color, y=190):
    """One line of text on a dark band across the middle of the picture (position messages)."""
    h, w = image.shape[:2]
    (tw, th), _ = cv2.getTextSize(text, FONT, 0.75, 2)
    fs = min(0.75, 0.75 * (w - 40) / max(tw, 1))
    (tw, th), _ = cv2.getTextSize(text, FONT, fs, 2)
    cv2.rectangle(image, ((w - tw) // 2 - 10, y - th - 10), ((w + tw) // 2 + 10, y + 10), (15, 15, 15), -1)
    cv2.putText(image, text, ((w - tw) // 2, y), FONT, fs, color, 2)
    return image


class ExitButton:
    """X button in the top-right corner of the shown picture, for the touch screen (no keyboard to press Q).
    Two taps exit: the first one turns it red with 'Tap again to exit' for CONFIRM_S seconds, so a stray touch
    during a curl does not close the app."""
    CONFIRM_S = 3.0

    def __init__(self, size=56, margin=8):
        self.size, self.margin = size, margin
        self.rect = None              # (x0, y0, x1, y1) where it was last drawn
        self.armed_at = None          # time of the first tap

    def armed(self, now):
        return self.armed_at is not None and now - self.armed_at < self.CONFIRM_S

    def tap(self, x, y, now):
        """A tap at (x, y) in the shown picture. Returns True when the app should close."""
        r = self.rect
        if r is None or not (r[0] <= x <= r[2] and r[1] <= y <= r[3]):
            self.armed_at = None      # a tap anywhere else cancels
            return False
        if self.armed(now):
            return True
        self.armed_at = now
        return False

    def draw(self, image, now):
        h, w = image.shape[:2]
        s, m = self.size, self.margin
        x0, y0 = w - s - m, m
        self.rect = (x0, y0, x0 + s, y0 + s)
        armed = self.armed(now)
        cv2.rectangle(image, (x0, y0), (x0 + s, y0 + s), (0, 0, 200) if armed else (60, 60, 60), -1)
        cv2.rectangle(image, (x0, y0), (x0 + s, y0 + s), (230, 230, 230), 2)
        p = s // 4
        for a, b in (((x0 + p, y0 + p), (x0 + s - p, y0 + s - p)), ((x0 + s - p, y0 + p), (x0 + p, y0 + s - p))):
            cv2.line(image, a, b, (255, 255, 255), 4, cv2.LINE_AA)
        if armed:
            text = "Tap again to exit"
            (tw, th), _ = cv2.getTextSize(text, FONT, 0.6, 2)
            tx, ty = x0 - tw - 12, y0 + (s + th) // 2
            cv2.rectangle(image, (tx - 6, ty - th - 8), (tx + tw + 6, ty + 8), (15, 15, 15), -1)
            cv2.putText(image, text, (tx, ty), FONT, 0.6, (255, 255, 255), 2)
        return image


def fit_to_screen(image, screen):
    """Enlarges the picture to fill a full-screen window, keeping its shape (black bars at the sides or top).
    OpenCV's Qt window shows a full-screen picture at its own size in the middle, so this is done here."""
    sw, sh = screen
    h, w = image.shape[:2]
    s = min(sw / w, sh / h)
    big = cv2.resize(image, (int(w * s), int(h * s)), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((sh, sw, 3), np.uint8)
    ox, oy = (sw - big.shape[1]) // 2, (sh - big.shape[0]) // 2
    canvas[oy:oy + big.shape[0], ox:ox + big.shape[1]] = big
    return canvas


def draw_qr_corner(image, qr, url, login_required=False):
    """Small QR code in the corner while someone stands there without being logged in."""
    h, w = image.shape[:2]
    if login_required:
        text = "Log in on your phone first - curls are not counted yet"
        (tw, th), _ = cv2.getTextSize(text, FONT, 0.7, 2)
        fs = min(0.7, 0.7 * (w - 20) / max(tw, 1))
        (tw, th), _ = cv2.getTextSize(text, FONT, fs, 2)
        cv2.rectangle(image, ((w - tw) // 2 - 8, 180), ((w + tw) // 2 + 8, 180 + th + 16), (15, 15, 15), -1)
        cv2.putText(image, text, ((w - tw) // 2, 188 + th), FONT, fs, (0, 200, 255), 2)
    size = 120
    big = cv2.resize(qr, (size, size), interpolation=cv2.INTER_NEAREST)
    big = cv2.cvtColor(cv2.copyMakeBorder(big, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255), cv2.COLOR_GRAY2BGR)
    x0, y0 = 10, h - 60 - big.shape[0] - 30
    image[y0:y0 + big.shape[0], x0:x0 + big.shape[1]] = big
    cv2.putText(image, "Scan to log in", (x0, y0 - 8), FONT, 0.5, (0, 200, 255), 2)
    return image
