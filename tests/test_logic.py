"""Tests for rep counting, calories and logging (no camera needed).
Run from the project folder with:  python tests/test_logic.py   (or: python -m pytest -q)"""

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fitform.bicep_curl import BicepCurlCounter, get_angle, measure_from_points
from fitform.calorie_tracker import CalorieTracker
from fitform.session_logger import SessionLogger, create_app


# ---------- helpers ----------
def arm(elbow_deg, torso_ok=True, wrist_ok=True):
    """2D arm points with a chosen elbow angle."""
    shoulder, elbow = [100, 100], [100, 200]            # upper arm pointing straight down
    rad = math.radians(elbow_deg)
    wrist = [100 + 100 * math.sin(rad), 200 - 100 * math.cos(rad)]
    hip = [100, 300] if torso_ok else [250, 200]        # swinging elbow -> big torso angle
    dx, dy = wrist[0] - elbow[0], wrist[1] - elbow[1]
    index = [wrist[0] + dx * 0.3, wrist[1] + dy * 0.3]  # straight wrist
    if not wrist_ok:
        index = [wrist[0] - dy * 0.3, wrist[1] + dx * 0.3]  # bent 90 degrees
    return {"shoulder": shoulder, "elbow": elbow, "wrist": wrist, "hip": hip, "index": index}


def m(elbow_deg, **kw):
    return measure_from_points(arm(elbow_deg, **kw))




# ---------- counting ----------
def test_angle():
    assert get_angle([0, 1], [0, 0], [1, 0]) == 90.0
    assert get_angle([0, 1], [0, 0], [0, -1]) == 180.0


def test_good_rep_counts():
    c = BicepCurlCounter("right", alpha=1.0)
    assert c.update(m(170), 0.0) is None
    assert c.update(m(90), 0.5) is None
    assert c.update(m(30), 1.0) == "counted"
    assert c.count == 1 and c.rep_times == [1.0]


def test_swinging_rep_rejected():
    c = BicepCurlCounter("right", alpha=1.0)
    c.update(m(170), 0.0)
    c.update(m(90, torso_ok=False), 0.5)
    assert c.update(m(30), 1.0) == "rejected"
    assert c.count == 0 and c.attempted == 1
    c.update(m(170), 2.0)
    assert c.update(m(30), 3.0) == "counted"


def test_bent_wrist_rejected():
    c = BicepCurlCounter("left", alpha=1.0)
    c.update(m(170), 0.0)
    assert c.update(m(30, wrist_ok=False), 1.0) == "rejected"



def test_smoothing_ignores_single_glitch():
    c = BicepCurlCounter("right", alpha=0.6)
    for t in range(5):
        c.update(m(170), t * 0.1)
    c.update(m(30), 0.6)           # one bad frame (e.g. landmark jump)
    assert c.count == 0            # smoothed elbow angle has not crossed 50 degrees yet


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
