"""Scores 'holding a weight / empty hand' models on the labelled crops of chosen rounds - through OpenCV's DNN
module, exactly as FitForm runs them - so a newly trained model can be compared with the one in use before it
replaces it. Runs in fitform_env (no PyTorch needed):
  python tools/eval_hand_classifier.py --rounds 4                                    # the model in models/
  python tools/eval_hand_classifier.py --rounds 4 --models models/hand_holding.onnx logs/cnn_candidate/hand_holding.onnx
Per picture and per curl-like 'vote' (the app decides once per rep: >= HOLD_EMPTY_RATIO of the readings 'empty'
= no weight), overall and by kind of hand."""

import argparse
import glob
import os
import re
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fitform import config  # noqa: E402
from fitform.hold_check import HoldClassifier  # noqa: E402

NAME = re.compile(r"^(?P<clip>[A-Za-z]+\d+)_(?P<cam>front|side)_(?P<arm>right|left)_(?P<frame>\d+)\.jpg$")
VOTE = 5            # readings per simulated rep (the app gets about 4-6 per rep)


def crops(rounds):
    out = []
    for rnd in rounds:
        for label in ("empty", "holding"):
            for p in sorted(glob.glob(os.path.join(ROOT, config.LOG_DIR, "hand_crops", rnd, label, "*.jpg"))):
                m = NAME.match(os.path.basename(p))
                if m:
                    out.append((p, label, m.groupdict()))
    return out


def kind(g, label):
    c = g["clip"].rstrip("0123456789")
    return f"{c.rstrip('Ls')} ({label})" if label == "holding" else f"empty ({c})"


def score(model_path, items):
    clf = HoldClassifier(model_path=model_path)
    rows = []
    for p, label, g in items:
        prob = clf.prob_holding(cv2.imread(p))
        rows.append((label, g, prob))
    lines = [f"== {os.path.relpath(model_path, ROOT)}"]
    ok = [("holding" if prob >= 0.5 else "empty") == label for label, _, prob in rows]
    lines.append(f"  per picture: {100 * np.mean(ok):5.1f} %  ({len(rows)} pictures)")
    groups = {}
    for (label, g, prob), good in zip(rows, ok):
        groups.setdefault(kind(g, label), []).append(good)
    for k in sorted(groups):
        lines.append(f"    {k:<22} {100 * np.mean(groups[k]):5.1f} %  ({len(groups[k])})")
    # per-rep vote, as in the app: consecutive readings of one hand in one clip, VOTE at a time
    seqs = {}
    for label, g, prob in rows:
        seqs.setdefault((g["clip"], g["cam"], g["arm"], label), []).append((int(g["frame"]), prob))
    votes = {}
    for (clip, cam, arm, label), seq in seqs.items():
        seq.sort()
        for i in range(0, len(seq) - VOTE + 1, VOTE):
            empty = sum(1 for _, pr in seq[i:i + VOTE] if pr < 0.5)
            said_empty = empty >= config.HOLD_EMPTY_RATIO * VOTE
            votes.setdefault(label, []).append(said_empty == (label == "empty"))
    for label in sorted(votes):
        lines.append(f"  per rep vote, {label:<8} {100 * np.mean(votes[label]):5.1f} %  ({len(votes[label])} votes)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", nargs="+", required=True, help="crop rounds to test on (logs/hand_crops/<round>)")
    ap.add_argument("--models", nargs="+", default=[os.path.join(ROOT, config.HOLD_MODEL)])
    args = ap.parse_args()
    items = crops(args.rounds)
    if not items:
        sys.exit(f"No crops for round(s) {' '.join(args.rounds)} - run tools/hand_crops.py first")
    print(f"Test pictures: {len(items)} from round(s) {' '.join(args.rounds)}")
    for m in args.models:
        print(score(os.path.abspath(m), items))


if __name__ == "__main__":
    main()
