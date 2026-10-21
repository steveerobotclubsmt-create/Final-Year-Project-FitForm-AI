"""Builds ~/fist_calib.json from four labelled --debug runs (front camera, arm straight, clenched fist):
  ~/r_good.txt  correct right-arm reps        ~/r_out.txt  right fist turned outward
  ~/l_good.txt  correct left-arm reps         ~/l_out.txt  left fist turned outward
Record them with (one per file, about 35 s each):
  timeout -s INT 35 python3 -u main.py --camera picam --rotate 180 --side-camera 0 --debug 2>&1 | tee ~/r_good.txt
Then:  python3 tools/fist_calibrate.py
Re-run the recordings whenever the FRONT camera is moved."""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fitform import config, fist_calib   # noqa: E402

LINE = re.compile(r"^\[([RL])\] elbow (\d+).*? hand fist .*?\(front ([+-]\d+\.\d+)")


def readings(path, arm_letter):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, errors="ignore") as fh:
        for ln in fh:
            m = LINE.match(ln)
            if m and m.group(1) == arm_letter and int(m.group(2)) > config.PALM_DIR_ELBOW_MIN:
                out.append(float(m.group(3)))
    return out


def main():
    folder = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~")
    calib = {}
    for arm, letter, pre in (("right", "R", "r"), ("left", "L", "l")):
        good = readings(os.path.join(folder, f"{pre}_good.txt"), letter)
        bad = readings(os.path.join(folder, f"{pre}_out.txt"), letter)
        print(f"{arm}: {len(good)} correct readings, {len(bad)} turned-out readings")
        if len(good) >= 5 and len(bad) >= 5:
            calib[arm] = {"good": good, "bad": bad}
        else:
            print(f"  not enough readings for the {arm} arm - record its two runs again")
    if not calib:
        print("nothing saved")
        return
    out = os.path.expanduser(config.FIST_CALIB_FILE)
    with open(out, "w") as fh:
        json.dump(calib, fh)
    print(f"saved {out}\n")
    # self-check: each recorded reading classified by the others (leave one out)
    print("arm    held        read as:  correct  turned-out  unclear")
    for arm, d in calib.items():
        for key, name in (("good", "correct"), ("bad", "turned out")):
            n = {"inward": 0, "outward": 0, "side": 0}
            for i, s in enumerate(d[key]):
                rest = {"good": list(d["good"]), "bad": list(d["bad"])}
                rest[key].pop(i)
                n[fist_calib.classify({arm: rest}, arm, s)] += 1
            print(f"{arm:6} {name:11}          {n['inward']:7d}  {n['outward']:10d}  {n['side']:7d}")


if __name__ == "__main__":
    main()
