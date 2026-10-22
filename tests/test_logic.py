"""Tests for rep counting, calories and logging (no camera needed).
Run from the project folder with:  python tests/test_logic.py   (or: python -m pytest -q)"""

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fitform import config
from fitform.bicep_curl import BicepCurlCounter, get_angle, measure_from_points, measure_from_world
from fitform.hand_state import classify_hand, palm_direction

# The basic counting tests below use short, simple sequences; the start-hold and tempo rules
# have their own tests further down, which switch them back on.
config.READY_HOLD_SECONDS = 0.0
config.MIN_UP_SECONDS = 0.0
config.FIST_CHECK = False      # the hand-check tests switch these on themselves
config.PALM_CHECK = False
config.STRAIGHT_CONFIRM_FRAMES = 1   # one frame per position in the short sequences below
config.TOP_CONFIRM_FRAMES = 1
config.FAULT_HOLD_SECONDS = 0.0      # faults count at once here; the hold time has its own tests
config.HAND_MIN_READINGS = 1
config.REJECT_PAUSE_SECONDS = 0.0   # the pause after a rejected rep has its own test
config.PALM_REJECTS = True          # the palm rules are tested as rejections; tip-only mode has its own test
config.OUTWARD_STREAK = 99          # the 'fist facing outward' streak pause has its own test
config.FIST_REJECTS = True          # grip rejections are tested; advisory mode has its own test
from fitform.calorie_tracker import CalorieTracker
from fitform.session_logger import SessionLogger, create_app


# ---------- helpers ----------
def arm(elbow_deg, drift_deg=0.0, wrist_ok=True):
    """2D arm points with a chosen elbow angle; drift_deg rotates the upper arm away from straight down."""
    d = math.radians(drift_deg)
    shoulder = [100.0, 100.0]
    ux, uy = math.sin(d), math.cos(d)                       # upper-arm direction (shoulder -> elbow)
    elbow = [shoulder[0] + 100 * ux, shoulder[1] + 100 * uy]
    a = math.radians(180 - elbow_deg)                       # forearm turns away from the upper-arm line
    fx, fy = ux * math.cos(a) - uy * math.sin(a), ux * math.sin(a) + uy * math.cos(a)
    wrist = [elbow[0] + 100 * fx, elbow[1] + 100 * fy]
    index = [wrist[0] + 30 * fx, wrist[1] + 30 * fy]        # straight wrist
    if not wrist_ok:
        index = [wrist[0] - 30 * fy, wrist[1] + 30 * fx]    # bent 90 degrees
    return {"shoulder": shoulder, "elbow": elbow, "wrist": wrist, "hip": [100, 300], "index": index}


def m(elbow_deg, **kw):
    return measure_from_points(arm(elbow_deg, **kw))


class P:
    def __init__(self, x, y, z=0.0, visibility=1.0):
        self.x, self.y, self.z, self.visibility = x, y, z, visibility


def hand(curled):
    """21 fake hand landmarks; `curled` fingers (index..little) have their tip folded back to the palm."""
    pts = [P(0.5, 0.9)] + [P(0.5, 0.9)] * 20
    for f, (tip, pip) in enumerate(((8, 6), (12, 10), (16, 14), (20, 18))):
        x = 0.42 + 0.05 * f
        pts[pip - 1] = P(x, 0.75)             # MCP
        pts[pip] = P(x, 0.62)                 # PIP
        pts[pip + 1] = P(x, 0.55)             # DIP
        pts[tip] = P(x, 0.72) if f < curled else P(x, 0.48)
    return pts


# ---------- counting ----------
def test_angle():
    assert get_angle([0, 1], [0, 0], [1, 0]) == 90.0
    assert get_angle([0, 1], [0, 0], [0, -1]) == 180.0
    assert get_angle([1, 0, 0], [0, 0, 0], [0, 0, 1]) == 90.0      # 3D works too


def test_good_rep_counts():
    c = BicepCurlCounter("right", alpha=1.0)
    assert c.update(m(170), 0.0) is None
    assert c.update(m(90), 0.5) is None
    assert c.update(m(30), 1.0) == "counted"
    assert c.count == 1 and c.rep_times == [1.0]


def test_small_natural_elbow_movement_still_counts():
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(90, drift_deg=12), 0.5)            # a little forward movement is normal
    assert c.update(m(30, drift_deg=15), 1.0) == "counted"


def test_swinging_rep_rejected():
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(90, drift_deg=40), 0.5)            # upper arm swings forward 40 degrees
    assert c.update(m(30, drift_deg=40), 1.0) == "rejected"
    assert c.count == 0 and c.attempted == 1 and "elbow moved" in c.last_reasons
    c.update(m(170), 2.0)
    assert c.update(m(30), 3.0) == "counted"


def test_failed_half_rep_does_not_block_next_rep():
    """A bad half rep (elbow moved, then lowered without reaching the top) must not stop the next good rep."""
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(100, drift_deg=45), 0.5)           # elbow swings, arm never reaches the top
    c.update(m(170), 1.0)                         # straightens again: fresh start
    c.update(m(90), 1.5)
    assert c.update(m(30), 2.0) == "counted"


def test_upper_arm_raised_to_the_side_is_rejected():
    """Upper arm must point down; curling with it held out to the side is not a bicep curl."""
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170, drift_deg=50), 0.0)
    c.update(m(90, drift_deg=55), 0.5)
    assert c.update(m(30, drift_deg=55), 1.0) == "rejected"
    assert c.last_reasons[0] == "upper arm not pointing down"


def test_elbow_moving_forward_is_rejected():
    """Front camera: elbow coming forward makes the upper arm look shorter against the shoulder width."""
    def mm(e, ratio):
        d = m(e)
        d["shoulder_w"], d["upper_len"] = 100.0, 85.0 * ratio
        return d
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(mm(170, 1.0), 0.0)
    c.update(mm(90, 0.6), 0.5)                    # elbow swung forward: upper arm looks 40 % shorter
    assert c.update(mm(30, 0.6), 1.0) == "rejected"
    assert c.last_reasons == ["elbow moved forward/back"]
    c.update(mm(170, 1.0), 2.0)
    c.update(mm(90, 0.97), 2.5)                   # normal curl: length hardly changes
    assert c.update(mm(30, 0.97), 3.0) == "counted"


def test_random_hand_turning_is_rejected():
    """Turning the hand back and forth during the lift: the side camera sees it (the front camera only
    judges the palm while the arm is straight)."""
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, palm="inward", side_palm="front")
    for t, e, p in ((0.1, 138, "outward"), (0.2, 133, "outward"), (0.3, 128, "front"),
                    (0.4, 124, "outward"), (0.5, 118, "outward"), (0.6, 113, "front")):
        c.update(m(e), t, palm="side", side_palm=p)     # mostly turned out (side camera needs a clear majority)
    assert c.update(m(35), 1.0, palm="side", side_palm="side") == "rejected"
    assert c.last_reasons == ["palm turned outward or backward"]
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_front_camera_ignores_palm_readings_mid_lift():
    """A correct fist reads 'outward' to the front camera once the forearm tilts (21 Oct log): ignored."""
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(172), 0.0, palm="inward")
    c.update(m(170), 0.1, palm="inward")
    for t, e in ((0.3, 140), (0.45, 126), (0.6, 114), (0.75, 90)):
        c.update(m(e), t, palm="outward")
    assert c.update(m(35), 1.0, palm="outward") == "counted"
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_rejected_rep_pauses_before_the_next_one():
    config.REJECT_PAUSE_SECONDS = 2.5
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(90, drift_deg=40), 0.5)
    assert c.update(m(30, drift_deg=40), 1.0) == "rejected"
    c.update(m(170), 1.5)                         # straight again, but still inside the pause ...
    c.update(m(90), 2.0)
    assert c.update(m(30), 2.5) is None           # ... so this curl is not started / counted
    c.update(m(170), 3.6)                         # after the pause: normal again
    c.update(m(90), 4.0)
    assert c.update(m(30), 4.5) == "counted"
    config.REJECT_PAUSE_SECONDS = 0.0


def test_bent_wrist_rejected():
    c = BicepCurlCounter("left", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(90, wrist_ok=False), 0.5)
    assert c.update(m(30, wrist_ok=False), 1.0) == "rejected"
    assert c.last_reasons == ["wrist bent"]


def test_smoothing_ignores_single_glitch():
    c = BicepCurlCounter("right", alpha=0.6)
    for t in range(5):
        c.update(m(170), t * 0.1)
    c.update(m(30), 0.6)           # one bad frame (e.g. landmark jump)
    assert c.count == 0            # smoothed elbow angle has not crossed 50 degrees yet


# ---------- fist check ----------
def test_classify_hand():
    assert classify_hand(hand(4)) == "fist"
    assert classify_hand(hand(3)) == "fist"
    assert classify_hand(hand(0)) == "open"
    assert classify_hand(hand(2)) == "fist"           # 2 bent fingers = gripping (bottle)
    assert classify_hand(hand(1)) == "open"


def grip_hand(bend_deg):
    """Fingers pointing down, each bent bend_deg at the PIP joint towards the camera (-z), like a hand
    round a bottle: the tips stay further from the wrist than the PIP joints in the picture."""
    pts = [P(0.5, 0.5, 0.0) for _ in range(21)]
    a = math.radians(bend_deg)
    for f, (mcp, pip, dip, tip) in enumerate(((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))):
        x = 0.46 + 0.025 * f
        pts[mcp] = P(x, 0.60, 0.0)
        pts[pip] = P(x, 0.66, 0.0)
        pts[dip] = P(x, 0.66 + 0.03 * math.cos(a), -0.03 * math.sin(a))
        pts[tip] = P(x, 0.66 + 0.06 * math.cos(a), -0.06 * math.sin(a))
    return pts


def test_side_camera_turned_out_rejects_rep():
    """Side camera has the same say as the front: 'turned out' during the rep = not counted."""
    config.PALM_CHECK = True
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, palm="front", side_palm="outward")
    c.update(m(130), 0.3, palm="front", side_palm="outward")
    c.update(m(90), 0.6, palm="front", side_palm="outward")
    assert c.update(m(35), 0.9, palm="front", side_palm="outward") == "rejected"
    assert c.last_reasons == ["palm turned outward or backward"]
    c.update(m(170), 2.0, palm="front", side_palm="front")      # good rep: side camera says ok
    c.update(m(170), 2.1, palm="front", side_palm="front")
    c.update(m(90), 2.6, palm="front", side_palm="side")        # unclear readings are not judged
    assert c.update(m(35), 2.9, palm="front", side_palm="front") == "counted"
    config.PALM_CHECK = False


def test_fist_turn_score_front_camera():
    """Index knuckle on the image right of the little-finger knuckle (right arm) = palm towards the body."""
    from fitform.hand_state import fist_turn_score
    def fist(index_x, pinky_x):
        pts = [P(0.5, 0.5, 0.0) for _ in range(21)]
        pts[5], pts[17] = P(index_x, 0.56), P(pinky_x, 0.56)
        return pts
    assert fist_turn_score(fist(0.47, 0.53), "right") > 0.5      # (palm_hand 'front' layout) -> out/forward
    assert fist_turn_score(fist(0.53, 0.47), "right") < -0.5     # mirror image -> towards the body
    assert fist_turn_score(fist(0.53, 0.47), "left") > 0.5       # same picture is the opposite for the left hand


def test_fist_calibration_per_arm():
    """Values from the labelled runs of 21 Oct: left sign reversed, right correct = edge-on (near 0)."""
    from fitform import fist_calib
    cal = {"left": {"good": [0.94, 0.98, 0.99, 0.81, 1.0, 0.96, 0.92], "bad": [-0.79, -0.61, -0.92, -0.99, -0.72, -0.9, -0.86]},
           "right": {"good": [0.04, 0.25, 0.42, -0.1, 0.13, -0.03, 0.36], "bad": [0.97, 0.95, -0.99, 0.98, -0.85, -0.97, 0.74]}}
    assert fist_calib.classify(cal, "left", 0.95) == "inward"
    assert fist_calib.classify(cal, "left", -0.9) == "outward"
    assert fist_calib.classify(cal, "right", 0.1) == "inward"
    assert fist_calib.classify(cal, "right", -0.95) == "outward"     # turned out reads either sign ...
    assert fist_calib.classify(cal, "right", 0.95) == "outward"      # ... for the right arm
    assert fist_calib.classify({}, "right", 0.1) is None             # not calibrated -> fixed rule is used


def test_palm_tip_only_mode_still_counts():
    config.PALM_CHECK, config.PALM_REJECTS, config.FAULT_HOLD_SECONDS = True, False, 0.3
    c = BicepCurlCounter("left", alpha=1.0)
    for t in (0.0, 0.1, 0.2, 0.3):
        c.update(m(171), t, palm="outward")                         # palm looks turned out ...
    c.update(m(120), 0.6, palm="side")
    assert c.update(m(35), 1.0, palm="side") == "counted"           # ... but the rep counts
    assert c.palm_tip is True
    c.update(m(170), 2.0, palm="inward")
    c.update(m(170), 2.1, palm="inward")
    c.update(m(90), 2.5, palm="side")
    assert c.update(m(35), 2.9, palm="side") == "counted" and c.palm_tip is False
    config.PALM_CHECK, config.PALM_REJECTS, config.FAULT_HOLD_SECONDS = False, True, 0.0


def test_three_outward_reps_in_a_row_pause():
    """Tip-only mode: reps still count, but the 3rd turned-out rep in a row pauses with a warning."""
    config.PALM_CHECK, config.PALM_REJECTS, config.FAULT_HOLD_SECONDS = True, False, 0.3
    config.OUTWARD_STREAK, config.OUTWARD_PAUSE_SECONDS, config.OUTWARD_PAUSE = 3, 3.0, True
    c = BicepCurlCounter("left", alpha=1.0)
    t = 0.0
    for rep in range(3):
        for _ in range(3):
            c.update(m(171), t, palm="outward"); t += 0.1
        c.update(m(120), t, palm="side"); t += 0.3
        assert c.update(m(35), t, palm="side") == "counted"; t += 0.5
        assert c.outward_alert is (rep == 2)
    assert c.count == 3 and c.blocked_until > t           # paused after the 3rd
    c.update(m(171), t, palm="inward"); c.update(m(90), t + 0.4); c.update(m(35), t + 0.8)
    assert c.count == 3                                     # nothing counts during the pause
    t += 3.5                                                # after the pause: a correct rep resets the streak
    for _ in range(3):
        c.update(m(171), t, palm="inward"); t += 0.1
    c.update(m(120), t, palm="side"); t += 0.3
    assert c.update(m(35), t, palm="side") == "counted" and not c.outward_alert and c.palm_streak == 0
    config.PALM_CHECK, config.PALM_REJECTS, config.FAULT_HOLD_SECONDS = False, True, 0.0
    config.OUTWARD_STREAK, config.OUTWARD_PAUSE = 99, False


def test_outward_warning_survives_one_missed_rep():
    """Turned out, turned out, (cameras read it as fine), turned out -> still 3 of the last 4."""
    config.PALM_CHECK, config.PALM_REJECTS, config.FAULT_HOLD_SECONDS = True, False, 0.3
    config.OUTWARD_STREAK, config.OUTWARD_WINDOW, config.OUTWARD_PAUSE = 3, 4, True
    c = BicepCurlCounter("left", alpha=1.0)
    t = 0.0
    for i, p in enumerate(("outward", "outward", "inward", "outward")):
        for _ in range(3):
            c.update(m(171), t, palm=p); t += 0.1
        c.update(m(120), t, palm="side"); t += 0.3
        c.update(m(35), t, palm="side"); t += 0.5
        assert c.outward_alert is (i == 3)
    config.PALM_CHECK, config.PALM_REJECTS, config.FAULT_HOLD_SECONDS = False, True, 0.0
    config.OUTWARD_STREAK, config.OUTWARD_PAUSE = 99, False


def test_demo_draws():
    import numpy as np
    from fitform.display_ui import draw_demo
    img = np.zeros((600, 800, 3), np.uint8)
    draw_demo(img, 1.3, 5.0)
    assert img.sum() > 0


def test_forearm_pointing_at_camera_does_not_end_the_rep():
    """Mid-lift the forearm points at the camera and the 2D angle can jump to ~5 deg for a few frames."""
    config.TOP_CONFIRM_FRAMES, config.MIN_UP_SECONDS = 2, 0.3
    def mm(e, fore):
        d = m(e)
        d["upper_len"], d["forearm_len"] = 100.0, fore
        return d
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(mm(170, 100), 0.0)
    c.update(mm(120, 70), 0.1)
    assert c.update(mm(5, 30), 0.15) is None          # squashed forearm: angle jump ignored ...
    assert c.update(mm(5, 25), 0.2) is None
    c.update(mm(40, 90), 0.5)
    assert c.update(mm(35, 92), 0.6) == "counted"     # ... the real top 0.6 s later counts (not 'too fast')
    config.TOP_CONFIRM_FRAMES, config.MIN_UP_SECONDS = 1, 0.0


def test_bottle_grip_counts_as_clenched():
    assert classify_hand(grip_hand(90)) == "fist"         # wrapped round a bottle
    assert classify_hand(grip_hand(15)) == "open"         # relaxed, nearly straight fingers


def test_open_hand_rep_rejected():
    config.FIST_CHECK = True
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, "open")
    for t, e in ((0.3, 120), (0.5, 90), (0.7, 70)):
        c.update(m(e), t, "open")
    assert c.update(m(30), 1.0, "open") == "rejected"
    assert c.last_reasons == ["hand not clenched"]
    config.FIST_CHECK = False


def test_open_hand_counts_when_fist_not_required():
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, "open")
    for t, e in ((0.3, 120), (0.5, 90), (0.7, 70)):
        c.update(m(e), t, "open")
    assert c.update(m(30), 1.0, "open") == "counted"


def test_fist_rep_counts():
    config.FIST_CHECK = True
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, "fist")
    for t, e in ((0.3, 120), (0.5, 90), (0.7, 70)):
        c.update(m(e), t, "fist")
    assert c.update(m(30), 1.0, "fist") == "counted"
    config.FIST_CHECK = False


def test_hidden_hand_is_not_counted():
    """Strict: if the hand is never seen, the rep cannot be checked, so it does not count."""
    config.FIST_CHECK = True
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, None)
    c.update(m(90), 0.5, None)
    assert c.update(m(30), 1.0, None) == "rejected"
    assert c.last_reasons == ["hand not visible"]
    config.FIST_CHECK = False


def test_3d_measurements():
    world = [P(0, 0, 0)] * 33
    world = list(world)
    world[12], world[14], world[16], world[20] = P(0, 0, 0), P(0, 0.3, 0), P(0, 0.3, -0.3), P(0, 0.3, -0.38)
    meas = measure_from_world(world, "right")
    assert meas["elbow"] == 90.0 and meas["wrist"] == 180.0


def test_engine_fist_rep_counts_with_knuckle_wrist():
    """Whole pipeline: pose points + MediaPipe Hands knuckle; a clean fist curl must count."""
    from fitform.feedback_engine import FeedbackEngine
    W, H = 960, 540

    class Pose:
        def __init__(self, elbow_deg):
            pts = arm(elbow_deg)
            self.landmark = [P(0.5, 0.5, 0, 0.0) for _ in range(33)]
            for j, i in (("shoulder", 12), ("elbow", 14), ("wrist", 16), ("index", 20)):
                x, y = pts[j]
                self.landmark[i] = P((W - x) / W, y / H, 0, 0.99)   # un-mirror like the real pipeline
            ex, ey = (W - pts["elbow"][0]), pts["elbow"][1]
            wx, wy = (W - pts["wrist"][0]), pts["wrist"][1]
            self.knuckle = ((wx, wy), (wx + (wx - ex) * 0.3, wy + (wy - ey) * 0.3))   # in line with forearm

    config.FIST_CHECK = True
    fe = FeedbackEngine()
    events = []
    for t, e in enumerate((170, 165, 130, 100, 70, 40)):
        pose = Pose(e)
        ev, _ = fe.update(pose, W, H, t * 0.2, world=None, hands={"right": "fist"}, hand_points={"right": pose.knuckle})
        events += ev
    assert ("right", "counted") in events, events
    config.FIST_CHECK = False


# ---------- palm direction (standard curl) ----------
def palm_hand(arm_name, facing):
    """Fake hand, fingers pointing down (arm hanging), seen in the un-mirrored camera image.
    Person's right hand, palm to the camera (standard grip): the thumb points away from the body,
    i.e. the index knuckle is on the image LEFT (the person's right side appears on the image left)."""
    pts = [P(0.5, 0.5) for _ in range(21)]
    pts[0] = P(0.50, 0.50)                                   # wrist
    s = -1 if (arm_name == "right") == (facing == "front") else 1
    pts[5] = P(0.50 + 0.03 * s, 0.56)                        # index knuckle
    pts[17] = P(0.50 - 0.03 * s, 0.56)                       # little-finger knuckle
    return pts


def test_palm_direction_both_hands():
    for a in ("right", "left"):
        assert palm_direction(palm_hand(a, "front"), a)[0] == "front"
        assert palm_direction(palm_hand(a, "back"), a)[0] == "back"


def _palm_rep(palms):
    """One rep; palms = palm direction for the frames at elbow 170 (start), 140, 125, 90, 70, 30."""
    config.PALM_CHECK = True
    c = BicepCurlCounter("right", alpha=1.0)
    ev = None
    c.update(m(172), -0.1, palm=palms[0])        # the down position lasts more than one frame
    for (t, e), p in zip(((0.0, 170), (0.3, 140), (0.5, 125), (0.7, 90), (0.85, 70), (1.0, 30)), palms):
        ev = c.update(m(e), t, palm=p)
    config.PALM_CHECK = False
    return ev, c


def test_palm_forward_rep_counts_even_if_back_seen_at_top():
    """Correct curl: palm to the camera at the bottom; the back of the hand faces the camera near the top."""
    ev, c = _palm_rep(["front", "front", "front", "back", "back", "back"])
    assert ev == "counted"


def test_reverse_grip_rep_rejected():
    ev, c = _palm_rep(["back", "back", "back", "back", "side", "side"])
    assert ev == "rejected" and c.last_reasons == ["palm turned outward or backward"]


def test_hand_turned_outward_rejected():
    ev, c = _palm_rep(["outward", "outward", "outward", "outward", "side", "side"])
    assert ev == "rejected" and c.last_reasons == ["palm turned outward or backward"]


def test_palm_facing_body_at_bottom_counts():
    """Palms towards the thighs at the start is a normal standard-curl start."""
    ev, c = _palm_rep(["inward", "inward", "front", "back", "back", "back"])
    assert ev == "counted"


def edge_hand(arm_name, thumb_towards_camera):
    """Hand hanging down, seen edge-on; index knuckle nearer (z < 0) or further from the camera."""
    d = -0.03 if thumb_towards_camera else 0.03
    pts = [P(0.5, 0.5, 0.0) for _ in range(21)]
    pts[5] = P(0.5, 0.56, d)
    pts[17] = P(0.5, 0.56, -d)
    return pts


def test_palm_inward_vs_outward_from_depth():
    for a in ("right", "left"):
        assert palm_direction(edge_hand(a, True), a)[0] == "inward"      # thumb forward = palm to body
        assert palm_direction(edge_hand(a, False), a)[0] == "outward"    # thumb back = palm away


# ---------- tempo + start position ----------
def test_too_fast_rep_rejected():
    config.MIN_UP_SECONDS = 0.6
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(90), 0.15)
    assert c.update(m(30), 0.3) == "rejected"
    assert c.last_reasons == ["too fast"]
    c.update(m(170), 1.0)
    c.update(m(90), 1.5)
    assert c.update(m(30), 2.0) == "counted"
    config.MIN_UP_SECONDS = 0.0


def test_no_count_before_start_position():
    """Arm swinging up as the person steps in must not count; holding it straight first arms the counter."""
    config.READY_HOLD_SECONDS = 0.5
    c = BicepCurlCounter("right", alpha=1.0)
    assert c.update(m(170), 0.0) is None          # straight only for a moment
    assert c.update(m(30), 0.2) is None           # curl right away: not ready, no rep
    c.update(m(170), 1.0)
    c.update(m(170), 1.6)                         # held straight 0.6 s -> ready
    c.update(m(90), 2.0)
    assert c.update(m(30), 2.5) == "counted"
    config.READY_HOLD_SECONDS = 0.0


# ---------- glitches and short detection gaps (real-camera behaviour) ----------
def test_one_frame_angle_jump_does_not_restart_the_rep():
    """Forearm pointing at the camera can make the 2D angle jump for a frame mid-lift."""
    config.STRAIGHT_CONFIRM_FRAMES, config.TOP_CONFIRM_FRAMES, config.MIN_UP_SECONDS = 2, 2, 0.4
    c = BicepCurlCounter("right", alpha=1.0)
    events = []
    for t, e in ((0.0, 170), (0.1, 170), (0.3, 130), (0.5, 90), (0.55, 170), (0.6, 70), (0.75, 40), (0.85, 35)):
        events.append(c.update(m(e), t))
    assert "counted" in events and c.count == 1 and c.rep_times[0] > 0.4
    config.STRAIGHT_CONFIRM_FRAMES, config.TOP_CONFIRM_FRAMES, config.MIN_UP_SECONDS = 1, 1, 0.0


def test_hand_hidden_briefly_during_lift_still_counts():
    config.FIST_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, "fist")
    c.update(m(170), 0.1, "fist")                 # good down position
    c.update(m(140), 0.3, None)                   # hand lost for 0.15 s
    c.update(m(120), 0.45, None)
    c.update(m(90), 0.6, "fist")
    assert c.update(m(35), 0.9, "fist") == "counted"
    config.FIST_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_hand_hidden_too_long_is_not_counted():
    config.FIST_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, "fist")
    for t, e in ((0.2, 138), (0.4, 130), (0.6, 120)):   # hand gone for 0.4 s in the lower part
        c.update(m(e), t, None)
    assert c.update(m(35), 1.0, None) == "rejected"
    assert c.last_reasons == ["hand not visible"]
    config.FIST_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_palm_turned_out_for_long_during_lift_rejected():
    """Hand turned out during the lift: the side camera catches it."""
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, palm="inward", side_palm="front")       # good start ...
    for t, e in ((0.2, 138), (0.4, 130), (0.6, 120)):              # ... then hand turned out for 0.4 s
        c.update(m(e), t, palm="side", side_palm="outward")
    assert c.update(m(35), 1.0, palm="side", side_palm="outward") == "rejected"
    assert c.last_reasons == ["palm turned outward or backward"]
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_palm_turned_out_at_the_bottom_rejected_by_front_camera():
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("left", alpha=1.0)                        # left arm: no side camera
    for t in (0.0, 0.1, 0.2, 0.3):
        c.update(m(171), t, palm="outward")
    c.update(m(120), 0.6, palm="side")
    assert c.update(m(35), 1.0, palm="side") == "rejected"
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_one_bad_palm_reading_is_ignored():
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, palm="front")
    c.update(m(138), 0.2, palm="outward")         # single blip
    c.update(m(125), 0.35, palm="front")
    c.update(m(90), 0.6, palm="back")             # back of hand near the top is normal
    assert c.update(m(35), 0.9, palm="back") == "counted"
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_unclear_palm_readings_do_not_fail_a_good_rep():
    """Fist seen from the front: many readings are 'side' (direction unclear). They must not count as wrong."""
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    for t, p in ((0.0, "side"), (0.1, "front"), (0.2, "side"), (0.3, "side"), (0.4, "inward")):
        c.update(m(170), t, palm=p)
    c.update(m(130), 0.6, palm="side")
    c.update(m(90), 0.8, palm="back")
    assert c.update(m(35), 1.0, palm="side") == "counted"
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_weak_wrong_palm_reading_is_unclear():
    pts = palm_hand("right", "back")
    pts[5].x, pts[17].x = 0.505, 0.495                        # nearly edge-on: weak 'back' reading
    pts[5].z = pts[17].z = 0.0
    label, front, inward = palm_direction(pts, "right", bad_min_score=0.55)
    assert label in ("back", "side")
    if abs(front) < 0.55:
        assert label == "side"
    assert palm_direction(palm_hand("right", "back"), "right", bad_min_score=0.55)[0] == "back"


def test_idle_arm_does_not_hide_the_active_arm_message():
    from fitform.feedback_engine import FeedbackEngine
    f = FeedbackEngine()
    f.counters["right"].ready = True
    f.counters["right"].last = {"hand_open": True}
    f.counters["left"].last = {"not_ready": True}             # left hand holding the phone
    f._set_message(["right", "left"])
    assert f.message == "RIGHT: Clench your fist"


# ---------- back-to-back reps ----------
def test_second_rep_counts_when_arm_only_lowered_to_about_145():
    """Doing reps back to back the arm often only comes down to ~140-150 degrees."""
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(90), 0.4)
    assert c.update(m(35), 0.8) == "counted"
    c.update(m(100), 1.2)
    c.update(m(145), 1.6)                         # lowered, but not above 150
    c.update(m(90), 2.0)
    assert c.update(m(35), 2.4) == "counted" and c.count == 2


def test_curling_again_without_lowering_is_reported():
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(90), 0.4)
    assert c.update(m(35), 0.8) == "counted"
    c.update(m(120), 1.2)                         # only half way down ...
    assert c.update(m(35), 1.6) == "rejected"     # ... and up again
    assert c.last_reasons == ["arm not straightened at the bottom"] and c.count == 1


def test_start_check_uses_the_end_of_the_previous_lowering():
    """Quick back-to-back reps: few straight frames, but the hand was seen while lowering."""
    config.FIST_CHECK, config.HAND_MIN_READINGS = True, 2
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, "fist")
    c.update(m(170), 0.1, "fist")
    c.update(m(90), 0.5, "fist")
    assert c.update(m(35), 0.9, "fist") == "counted"
    c.update(m(120), 1.2, "fist")                 # lowering, hand seen
    c.update(m(135), 1.3, "fist")
    c.update(m(142), 1.4, None)                   # one straight frame, hand missed
    c.update(m(90), 1.8, "fist")
    assert c.update(m(35), 2.2, "fist") == "counted"
    config.FIST_CHECK, config.HAND_MIN_READINGS = False, 1


# ---------- calories + logging ----------
def test_calories():
    t = CalorieTracker(weight_kg=70, met=3.5)
    assert t.calories(100) == 0
    t.on_rep(0)
    assert abs(t.calories(3600) - 245.0) < 1e-6


def test_session_ends_when_walking_away_or_idle():
    from fitform.session import SessionTracker
    t = SessionTracker(away_s=5, idle_s=30)
    assert t.update(0.0, True, False) is False          # no curl yet: no session
    assert t.update(1.0, True, True) is False           # first curl starts it
    assert t.update(5.0, False, False) is False         # out of view 4 s
    assert t.update(6.5, False, False) is True          # out of view > 5 s -> end
    t.end()
    t.update(10.0, True, True)
    assert t.update(39.0, True, False) is False
    assert t.seconds_left(30.0) == 10.0                 # countdown for the screen
    assert t.update(40.5, True, False) is True          # standing there, no curl for > 30 s -> end


def test_summary_and_goal():
    from fitform.feedback_engine import FeedbackEngine
    from fitform.plan import goal_for, make_plan
    from fitform.session_summary import build_summary
    f = FeedbackEngine()
    r, l = f.counters["right"], f.counters["left"]
    r.count, r.attempted, r.rep_times, r.reject_counts, r.palm_flags, r.grip_flags = 24, 25, [1.0] * 24, {"fast": 1}, 2, 3
    l.count, l.attempted, l.rep_times = 24, 26, [1.2] * 24
    l.reject_counts = {"arm_tilt": 2}
    cal = CalorieTracker(weight_kg=80)
    cal.on_rep(0.0)
    s = build_summary(f, cal, 120.0, snapshots=["a_right_palm_1.jpg"], user="steve")
    assert s["reps_total"] == 48 and s["attempted_total"] == 51 and s["weight_kg"] == 80 and s["user"] == "steve"
    assert s["not_counted"] == {"upper arm not pointing down": 2, "too fast": 1}
    g0 = goal_for(0, 80)
    assert (g0["sets"], g0["reps"], g0["total_reps"]) == (3, 8, 48)
    # kcal goal = MET 3.5 x 80 kg x planned time (48 reps x 3 s + 5 rests x 60 s = 444 s)
    assert abs(g0["kcal"] - round(3.5 * 80 * 444 / 3600, 1)) < 0.05
    p = make_plan(s, [], 80)                              # 24 per arm >= 3x8 with 94 % counted -> step up
    assert p["met_goal"] and p["goal"]["reps"] == 10
    assert p["palm_warning"] and p["grip_warning"]
    low = make_plan({**s, "form_accuracy_pct": 50.0}, [], 80)
    assert not low["met_goal"] and low["goal"]["reps"] == 8
    # at 3x12: the first time 'repeat once more', the second time in a row 'add weight' and back to 3x8
    at12 = {**s, "reps_right": 36, "reps_left": 36, "reps_total": 72}
    rec12 = {"summary": at12, "plan": {"goal": goal_for(2, 80)}}
    first = make_plan(at12, [rec12], 80)
    assert first["goal"]["reps"] == 12 and "Repeat" in first["headline"]
    second = make_plan(at12, [rec12, {"summary": at12, "plan": first}], 80)
    assert second["goal"]["reps"] == 8 and "2-10 %" in second["weight"]


def test_grip_is_advisory_by_default():
    config.FIST_CHECK, config.FIST_REJECTS = True, False
    c = BicepCurlCounter("right", alpha=1.0)
    for t in (0.0, 0.1, 0.2):
        c.update(m(170), t, "open")
    c.update(m(90), 0.5, "open")
    assert c.update(m(30), 1.0, "open") == "counted" and c.grip_flags == 1 and c.grip_flag_last
    config.FIST_CHECK, config.FIST_REJECTS = False, True


def test_device_login_times_out():
    with tempfile.TemporaryDirectory() as d:
        log = SessionLogger(log_dir=d)
        log.set_device_user("steve")
        assert log.device_user() == "steve"
        log._device_until = 0
        assert log.device_user() is None


def test_camera_detection_and_roles():
    from fitform.camera_detect import choose, parse_rpicam_list, parse_v4l2_devices
    # outputs pasted from the Pi on 21 Oct
    rp = """Available cameras
-----------------
0 : imx500 [4056x3040 10-bit RGGB] (/base/axi/pcie@1000120000/rp1/i2c@80000/imx500@1a)
    Modes: 'SRGGB10_CSI2P' : 2028x1520 [30.02 fps - (0, 0)/4056x3040 crop]"""
    assert parse_rpicam_list(rp) and not parse_rpicam_list("No cameras available!")
    v4l = """pispbe (platform:1000880000.pisp_be):
        /dev/video20
        /dev/video21

rpi-hevc-dec (platform:rpi-hevc-dec):
        /dev/video19

C270 HD WEBCAM (usb-xhci-hcd.0-2):
        /dev/video0
        /dev/video1
"""
    assert parse_v4l2_devices(v4l) == [0]
    assert choose(True, [0]) == ("picam", 0)       # both: AI camera front, webcam side
    assert choose(True, []) == ("picam", None)     # AI camera only
    assert choose(False, [0]) == (0, None)         # no AI camera: webcam is the front
    assert choose(False, [0, 2]) == (0, 2)         # two webcams: second one at the side
    assert choose(False, []) == (None, None)       # nothing found


def test_logger_accounts_and_app():
    with tempfile.TemporaryDirectory() as d:
        log = SessionLogger(log_dir=d)
        assert log.register("st", "secret1", 70)                  # username too short -> error text
        assert log.register("steve", "123", 70)                   # password too short
        assert log.register("steve", "secret1", 82) is None
        assert log.register("Steve", "other12", 70)               # taken (case-insensitive)
        assert log.check_login("steve", "secret1") and not log.check_login("steve", "wrong")
        assert "secret1" not in open(log.users_path).read()       # stored hashed
        client = create_app(log, secret_key="test").test_client()
        assert "Log in" in client.get("/").get_data(as_text=True)
        assert client.post("/login", data={"username": "steve", "password": "wrong"}).status_code == 302
        assert "Log in" in client.get("/").get_data(as_text=True)
        client.post("/login", data={"username": "steve", "password": "secret1"})
        page = client.get("/").get_data(as_text=True)
        assert "Hi steve" in page and "Next session goal" in page and "3 sets &times; 8 reps" in page
        client.post("/start")
        assert log.device_user() == "steve"
        assert "ready for you" in client.get("/").get_data(as_text=True)
        from fitform.plan import goal_for
        s = {"timestamp": "2026-10-22 10:00:00", "user": "steve", "exercise": "bicep_curl", "reps_right": 3,
             "reps_left": 2, "reps_total": 5, "attempted_total": 6, "form_accuracy_pct": 83.3, "duration_s": 61.0,
             "calories_kcal": 1.2, "avg_rep_speed_s": 0.8, "not_counted": {"too fast": 1}, "snapshots": []}
        log.save(s, {"headline": "Same goal", "goal": goal_for(1, 82), "this_goal": goal_for(0, 82),
                     "weight": "Keep the same weight.", "focus": [], "notes": [], "rest": "Rest.", "met_goal": False})
        log.save({**s, "user": "anna"}, None)                     # someone else's session
        page = client.get("/").get_data(as_text=True)
        assert "Calories per session" in page and "3 sets &times; 10 reps" in page
        assert len(client.get("/sessions").get_json()) == 1       # only my sessions
        assert "steve" in client.get("/sessions.csv").get_data(as_text=True)
        assert client.get("/snap/someone_else.jpg").status_code == 404
        client.get("/logout")
        assert "Log in" in client.get("/").get_data(as_text=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("passed", name)
