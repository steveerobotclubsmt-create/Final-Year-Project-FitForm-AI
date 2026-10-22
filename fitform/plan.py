"""Goal for the next session - rules taken from published guidelines, so the numbers have a source.

  Sets/reps : novices 1-3 sets of 8-12 reps per exercise; increase the load by 2-10 % once the current
              load can be done for 1-2 reps more than planned on two consecutive sessions.
              (Ratamess et al., ACSM position stand, Med Sci Sports Exerc 2009;41(3):687-708)
  Rest      : 1-2 min between sets for assistance exercises such as curls (same source).
  Frequency : muscle-strengthening activity on at least 2 days a week (WHO Guidelines on Physical
              Activity and Sedentary Behaviour, 2020).
  kcal      : MET 3.5 for 'resistance (weight) training, multiple exercises, 8-15 reps' (2024 Adult
              Compendium of Physical Activities, code 02054); kcal = MET x body weight (kg) x hours.

The goal climbs a ladder 3x8 -> 3x10 -> 3x12 reps per arm; after two sessions in a row at 3x12 with good
form it advises a small weight increase and starts again at 3x8. General guidance, not coaching."""

from datetime import datetime, timedelta

from . import config
from .bicep_curl import FIX_TEXT

LADDER = [(3, 8), (3, 10), (3, 12)]     # (sets, reps per set) per arm
GOOD_FORM = 85.0                         # % of curls counted to move up
OK_FORM = 70.0                           # below this: form first
SEC_PER_REP = 3.0                        # slow-moderate tempo: about 1 s up, 2 s down
REST_S = 60.0                            # between sets (1-2 min recommended; lower end used)
WEEKLY_SESSIONS = 2                      # WHO 2020: at least 2 days a week

SOURCES = [
    "Ratamess et al. (2009) ACSM position stand: Progression models in resistance training for healthy "
    "adults. Med Sci Sports Exerc 41(3):687-708 - sets, reps, rest, 2-10 % load increase.",
    "World Health Organization (2020) Guidelines on physical activity and sedentary behaviour - "
    "muscle-strengthening on at least 2 days a week.",
    "Herrmann et al. (2024) Adult Compendium of Physical Activities, code 02054: resistance training "
    "8-15 reps = 3.5 MET.",
]


def goal_for(step, weight_kg):
    sets, reps = LADDER[step]
    planned_s = 2 * sets * reps * SEC_PER_REP + (2 * sets - 1) * REST_S     # both arms, rests in between
    kcal = config.MET_BICEP_CURL * weight_kg * planned_s / 3600.0
    return {"step": step, "sets": sets, "reps": reps, "reps_per_arm": sets * reps,
            "total_reps": 2 * sets * reps, "kcal": round(kcal, 1), "minutes": round(planned_s / 60.0, 1)}


def _met(s, goal):
    r, l = s.get("reps_right", 0), s.get("reps_left", 0)
    weakest = min(r, l) if (r and l) else max(r, l)
    return weakest >= goal["reps_per_arm"] and s.get("form_accuracy_pct", 0) >= GOOD_FORM


def make_plan(s, history=None, weight_kg=None):
    """s: this session's summary. history: this user's earlier records [{'summary','plan'}] oldest first.
    Returns the plan incl. 'goal' for the next session (stored with the session, so the next one is judged
    against it)."""
    history = [h for h in (history or []) if (h.get("summary") or {}).get("attempted_total")]
    weight_kg = weight_kg or s.get("weight_kg") or config.USER_WEIGHT_KG
    prev_plan = (history[-1].get("plan") or {}) if history else {}
    current = prev_plan.get("goal") or goal_for(0, weight_kg)          # the goal this session was aimed at
    step = current.get("step", 0)
    acc = s.get("form_accuracy_pct", 0.0)
    r, l = s.get("reps_right", 0), s.get("reps_left", 0)
    plan = {"focus": [], "notes": [], "progress": None, "palm_warning": None, "grip_warning": None,
            "this_goal": current, "met_goal": _met(s, current), "weight": "Keep the same weight."}

    if plan["met_goal"]:
        if step < len(LADDER) - 1:
            step += 1
            plan["headline"] = "Goal reached! Next time: a few more reps"
        else:
            prev_met = bool(history) and (history[-1].get("plan") or {}).get("met_goal") and \
                (history[-1].get("plan") or {}).get("this_goal", {}).get("step") == len(LADDER) - 1
            if prev_met:
                step = 0
                plan["headline"] = "Two strong sessions in a row - time for a heavier weight"
                plan["weight"] = ("Increase the weight by 2-10 % (about 0.5-1 kg for a dumbbell curl) and start "
                                  "again at 3 sets of 8.")
            else:
                plan["headline"] = "Goal reached! Repeat it once more, then add weight"
    elif acc < OK_FORM and s.get("attempted_total", 0) >= 5:
        plan["headline"] = "Same goal - focus on clean reps first"
        plan["weight"] = "If many reps are not counted, use a lighter weight until the form is right."
    else:
        plan["headline"] = "Same goal next time - you are getting there"
    plan["goal"] = goal_for(step, weight_kg)

    reasons = sorted((s.get("not_counted_keys") or {}).items(), key=lambda kv: -kv[1])
    for key, n in reasons[:2]:
        if key in FIX_TEXT:
            plan["focus"].append(f"{FIX_TEXT[key]} ({n} curl{'s' if n != 1 else ''} not counted for this)")
    lift = s.get("avg_rep_speed_s", 0.0)
    if 0 < lift < 0.6 and "fast" not in dict(reasons[:2]):
        plan["notes"].append("Slow down a little: about 1 second up and 2 seconds down.")
    if r and l and abs(r - l) >= 3 and abs(r - l) >= 0.25 * max(r, l):
        weak = "left" if l < r else "right"
        plan["notes"].append(f"Your {weak} arm did fewer reps ({min(r, l)} vs {max(r, l)}). Start with it next time.")
    elif not (r and l) and (r or l):
        plan["notes"].append(f"Only one arm was trained - remember your {'left' if r else 'right'} arm.")
    if history:
        prev = history[-1]["summary"]
        d_reps = s.get("reps_total", 0) - int(prev.get("reps_total", 0) or 0)
        d_kcal = s.get("calories_kcal", 0) - float(prev.get("calories_kcal", 0) or 0)
        plan["progress"] = f"{'+' if d_reps >= 0 else ''}{d_reps} reps, {'+' if d_kcal >= 0 else ''}{d_kcal:.1f} kcal vs last session."

    flags = s.get("palm_flags_right", 0) + s.get("palm_flags_left", 0)
    if flags >= config.OUTWARD_WARN_MIN:
        plan["palm_warning"] = (f"The cameras think your fist was turned outward in {flags} reps. This reading is not "
                                "always accurate, so check the pictures. Keep your fist facing your body (parallel to "
                                "it): curling with the fist turned out can strain the wrist and elbow.")
    grips = s.get("grip_flags_right", 0) + s.get("grip_flags_left", 0)
    if grips >= config.OUTWARD_WARN_MIN:
        plan["grip_warning"] = (f"Your hand looked open in {grips} reps. With a bottle or dumbbell this can be a camera "
                                "error - check the pictures. Hold the weight firmly in your fist.")
    plan["rest"] = "Rest your biceps about 48 hours; aim for at least 2 sessions a week."
    return plan


def week_count(history, now=None):
    """Sessions of this user in the last 7 days (WHO: at least 2 days a week)."""
    now = now or datetime.now()
    n = 0
    for h in history:
        try:
            t = datetime.strptime(h["summary"]["timestamp"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            continue
        if now - t <= timedelta(days=7):
            n += 1
    return n
