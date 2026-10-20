"""Palm direction from a per-user calibration (tools/palm_calibrate.py -> ~/palm_calib.csv).

Why: for a clenched fist the hand model's depth (z) guesses do not follow the textbook geometry, so a
fixed formula misread 'fist turned outward' as 'palm forward' (measured 20 Oct). The calibration records
several cues while the user holds each position; live readings are then given the label of the nearest
recorded position (nearest-centroid classifier, each cue scaled by its spread)."""

import csv
import math
import os

CLASSES = ("inward", "front", "outward", "back")
GOOD = ("inward", "front")
FEATURES = ("front", "inward", "thumb_depth", "thumb_side", "knuckle_side", "pinky_depth")


def hand_features(b, arm, w, h, front, inward):
    """Cues from the 21 hand landmarks of the un-mirrored image (front/inward from palm_direction)."""
    to_mid = 1.0 if arm == "right" else -1.0          # +x is towards the body for the right arm
    size = math.hypot((b[9].x - b[0].x) * w, (b[9].y - b[0].y) * h) or 1.0
    return {
        "front": front,
        "inward": inward,
        "thumb_depth": (b[4].z - b[17].z) * w / size,                 # thumb tip vs little-finger knuckle depth
        "thumb_side": (b[4].x - b[17].x) * w * to_mid / size,         # thumb tip towards the body (2D)
        "knuckle_side": (b[5].x - b[17].x) * w * to_mid / size,       # index knuckle towards the body (2D)
        "pinky_depth": (b[5].z - b[17].z) * w / size,                 # index vs little-finger knuckle depth
    }


def _base(pos):
    return pos.rstrip("0123456789")                    # 'inward2' -> 'inward'


def _median(v):
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def fit(rows):
    """rows: dicts with 'pos' and the FEATURES. Returns the model, or None if a position is missing.
    Medians (not averages) so a few readings taken in the wrong position do not move the centre."""
    groups = {c: [r for r in rows if _base(r["pos"]) == c] for c in CLASSES}
    if any(len(g) < 3 for g in groups.values()):
        return None
    means = {c: {f: _median([r[f] for r in g]) for f in FEATURES} for c, g in groups.items()}
    scale = {}
    for f in FEATURES:                                  # robust spread (MAD) of each cue within the positions
        dev = [abs(r[f] - means[c][f]) for c, g in groups.items() for r in g]
        scale[f] = max(1.4826 * _median(dev), 0.05)
    return {"means": means, "scale": scale}


def classify(model, feats, margin=0.5):
    """Returns (label, d_good, d_bad). Label is 'side' (unclear) when good and bad are about equally close."""
    d = {}
    for c in CLASSES:
        m = model["means"][c]
        d[c] = math.sqrt(sum(((feats[f] - m[f]) / model["scale"][f]) ** 2 for f in FEATURES))
    d_good = min(d[c] for c in GOOD)
    d_bad = min(d[c] for c in CLASSES if c not in GOOD)
    if abs(d_good - d_bad) < margin:
        return "side", d_good, d_bad
    return min(d, key=d.get), d_good, d_bad


def read_rows(path):
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append({"pos": r["pos"], **{f: float(r[f]) for f in FEATURES}})
            except (TypeError, ValueError, KeyError):
                continue                               # a reading with a missing value
    return rows


def load(path):
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return None
    return fit(read_rows(path))


def check(rows, margin=0.5):
    """Leave-one-position-out style check: fit on all, report how each recorded reading is classified."""
    model = fit(rows)
    if model is None:
        return None, {}
    table = {}
    for r in rows:
        lab = classify(model, r, margin)[0]
        key = _base(r["pos"])
        table.setdefault(key, {}).setdefault(lab, 0)
        table[key][lab] += 1
    return model, table
