"""Front-camera fist direction from labelled calibration runs (tools/fist_calibrate.py -> ~/fist_calib.json).

Why: the 2D fist reading (hand_state.fist_turn_score) separates a correct fist from a turned-out one very
clearly, but HOW depends on where the camera stands and on the arm. Labelled runs on 21 Oct (front AI
camera on the PC tower):
  left arm : correct +0.81..+1.00, turned out -0.61..-0.99   (sign reversed vs. the 20 Oct webcam set-up)
  right arm: correct about -0.1..+0.5 (seen edge-on), turned out about +-0.7..1.0 (either sign)
So each arm keeps its own recorded 'correct' and 'turned out' readings, and a live reading gets the label
whose recorded readings it is most like (a smoothed histogram per class; works for two clusters too)."""

import json
import math
import os


def load(path):
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        data = json.load(fh)
    ok = {a: d for a, d in data.items() if len(d.get("good", [])) >= 5 and len(d.get("bad", [])) >= 5}
    return ok or None


def _density(x, samples, bw):
    return sum(math.exp(-0.5 * ((x - s) / bw) ** 2) for s in samples) / len(samples)


def classify(calib, arm, score, bw=0.15, ratio=2.0):
    """'inward' (correct), 'outward' (wrong) or 'side' (unclear) - or None if this arm is not calibrated."""
    d = calib.get(arm) if calib else None
    if d is None:
        return None
    pg, pb = _density(score, d["good"], bw), _density(score, d["bad"], bw)
    if pg > ratio * pb:
        return "inward"
    if pb > ratio * pg:
        return "outward"
    return "side"
