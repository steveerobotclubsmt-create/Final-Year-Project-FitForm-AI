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
    assert c.count == 0 and c.attempted == 1 and c.last_reasons == ["elbow moved"]
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


def test_side_raised_arm_is_not_a_false_swing():
    """Arm held out to the side from the start (front view): the start position is the reference."""
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170, drift_deg=50), 0.0)
    c.update(m(90, drift_deg=55), 0.5)
    assert c.update(m(30, drift_deg=55), 1.0) == "counted"


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
    assert classify_hand(hand(2)) == "partial"


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
    assert ev == "rejected" and c.last_reasons == ["palm not facing forward"]


def test_hand_turned_outward_rejected():
    """Hand rotated out to the side: the camera sees the edge of the hand, never the palm."""
    ev, c = _palm_rep(["side", "side", "side", "side", "side", "side"])
    assert ev == "rejected" and c.last_reasons == ["palm not facing forward"]


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
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, palm="front")           # good start ...
    for t, e in ((0.2, 140), (0.4, 130), (0.6, 120)):   # ... then hand turned out for 0.4 s
        c.update(m(e), t, palm="side")
    assert c.update(m(35), 1.0, palm="back") == "rejected"
    assert c.last_reasons == ["palm not facing forward"]
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


def test_one_bad_palm_reading_is_ignored():
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = True, 0.3
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0, palm="front")
    c.update(m(140), 0.2, palm="side")            # single blip
    c.update(m(125), 0.35, palm="front")
    c.update(m(90), 0.6, palm="back")             # back of hand near the top is normal
    assert c.update(m(35), 0.9, palm="back") == "counted"
    config.PALM_CHECK, config.FAULT_HOLD_SECONDS = False, 0.0


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


def test_logger_and_flask():
    with tempfile.TemporaryDirectory() as d:
        log = SessionLogger(log_dir=d)
        log.save({"exercise": "bicep_curl", "reps_total": 5})
        log.save({"exercise": "bicep_curl", "reps_total": 7})
        client = create_app(log).test_client()
        rows = client.get("/sessions").get_json()
        assert [r["reps_total"] for r in rows] == ["5", "7"]
        assert client.get("/sessions.csv").status_code == 200


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("passed", name)
