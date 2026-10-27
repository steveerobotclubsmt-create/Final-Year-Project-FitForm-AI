"""Builds the end-of-session totals, prints them, and hands them to the logger."""

from datetime import datetime

from .bicep_curl import REASON_TEXT


def _avg(v):
    return round(sum(v) / len(v), 2) if v else 0.0


def build_summary(feedback, calories, end_time, exercise="bicep_curl", snapshots=None, user=None):
    """end_time: when the last curl finished (so standing around before walking away is not counted)."""
    right, left = feedback.counters["right"], feedback.counters["left"]
    reps_total = right.count + left.count
    attempted = right.attempted + left.attempted
    reasons = {}
    for c in (right, left):
        for k, n in c.reject_counts.items():
            reasons[k] = reasons.get(k, 0) + n
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "exercise": exercise,
        "reps_right": right.count,
        "reps_left": left.count,
        "reps_total": reps_total,
        "attempted_right": right.attempted,
        "attempted_left": left.attempted,
        "attempted_total": attempted,
        "form_accuracy_pct": round(100.0 * reps_total / attempted, 1) if attempted else 0.0,
        "duration_s": round(calories.active_seconds(end_time), 1),
        "calories_kcal": round(calories.calories(end_time), 2),
        "avg_rep_speed_s": _avg(right.rep_times + left.rep_times),
        "avg_lift_right_s": _avg(right.rep_times),
        "avg_lift_left_s": _avg(left.rep_times),
        "not_counted": {REASON_TEXT.get(k, k): n for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])},
        "not_counted_keys": reasons,
        "palm_flags_right": right.palm_flags,
        "palm_flags_left": left.palm_flags,
        "grip_flags_right": right.grip_flags,
        "grip_flags_left": left.grip_flags,
        "weight_flags_right": right.weight_flags,
        "weight_flags_left": left.weight_flags,
        "snapshots": list(snapshots or []),
        "user": user or "guest",
        "weight_kg": calories.weight_kg,
    }


def print_summary(s, plan=None):
    print("\n========== SESSION SUMMARY ==========")
    print(f"Right reps     : {s['reps_right']} (of {s.get('attempted_right', '-')} curls)")
    print(f"Left reps      : {s['reps_left']} (of {s.get('attempted_left', '-')} curls)")
    print(f"Form accuracy  : {s['form_accuracy_pct']}% ({s['reps_total']}/{s['attempted_total']} curls counted)")
    print(f"Active time    : {s['duration_s']} s")
    print(f"Calories       : {s['calories_kcal']} kcal")
    print(f"Avg rep speed  : {s['avg_rep_speed_s']} s/rep")
    for why, n in s.get("not_counted", {}).items():
        print(f"Not counted    : {n} x {why}")
    if plan:
        print(f"Next time      : {plan['headline']}")
    print("=====================================\n")
