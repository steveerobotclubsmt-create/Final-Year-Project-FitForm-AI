"""Builds the end-of-session totals, prints them, and hands them to the logger."""

from datetime import datetime


def build_summary(feedback, calories, now, exercise="bicep_curl"):
    right = feedback.counters["right"]
    left = feedback.counters["left"]
    reps_total = right.count + left.count
    attempted = right.attempted + left.attempted
    rep_times = right.rep_times + left.rep_times
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "exercise": exercise,
        "reps_right": right.count,
        "reps_left": left.count,
        "reps_total": reps_total,
        "attempted_total": attempted,
        "form_accuracy_pct": round(100.0 * reps_total / attempted, 1) if attempted else 0.0,
        "duration_s": round(calories.active_seconds(now), 1),
        "calories_kcal": round(calories.calories(now), 2),
        "avg_rep_speed_s": round(sum(rep_times) / len(rep_times), 2) if rep_times else 0.0,
    }


def print_summary(s):
    print("\n========== SESSION SUMMARY ==========")
    print(f"Right reps     : {s['reps_right']}")
    print(f"Left reps      : {s['reps_left']}")
    print(f"Form accuracy  : {s['form_accuracy_pct']}% ({s['reps_total']}/{s['attempted_total']} curls counted)")
    print(f"Active time    : {s['duration_s']} s")
    print(f"Calories       : {s['calories_kcal']} kcal")
    print(f"Avg rep speed  : {s['avg_rep_speed_s']} s/rep")
    print("=====================================\n")
