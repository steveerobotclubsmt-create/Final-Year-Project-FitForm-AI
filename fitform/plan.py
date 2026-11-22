"""Goal for the next session - rules taken from published guidelines, so the numbers have a source.
Every rule below was checked against the source's own text on 16 Nov 2026 (quotes and pages in SOURCES).

  Sets/reps : ACSM 2009, p. 691: "one to three sets per exercise be used by novice individuals initially";
              p. 694: "8-12 repetitions per set for one to three sets per exercise" (novice and intermediate).
              ACSM 2026 update: "healthy adults are advised to complete at least two sets per exercise".
  Load      : ACSM 2009, p. 690: "2-10% (lower percent for small muscle mass exercises, higher percent increase
              for large muscle mass exercises) increase in load be applied when the individual can perform the
              current workload for one to two repetitions over the desired number on two consecutive training
              sessions". FitForm moves up after reaching the 3x12 goal on two sessions in a row - an
              adaptation of that rule - and suggests the lower end, as the biceps are a small muscle group.
  Rest      : ACSM 2009, p. 692: "For assistance exercises (those exercises complimentary to core exercises),
              a shorter rest period length of 1-2 min may suffice".
  Frequency : WHO 2020, Table 4: "on 2 or more days a week".
  kcal      : 2024 Adult Compendium, code 02054 = 3.5 MET. Formula from the Compendium website (Unit
              Conversions, https://pacompendium.com/unite-conversions/): "METS to Kcal/min = multiply METS x 3.5
              x body weight in kg then divide by 200" - the paper (section 2.5) says "Additional equations used to
              convert EE values are available on the Compendium website". It notes the values do "not reflect
              precise individual EE values".

The goal climbs a ladder 3x8 -> 3x10 -> 3x12 reps per arm; after two goal sessions in a row at 3x12 with good
form it advises a small weight increase and starts again at 3x8. Only 'Follow my goal' sessions (workout.py) move
the ladder; a 'Challenge yourself' session keeps the goal and can set a personal best. Sessions saved before the
two ways existed count as goal sessions. General guidance, not coaching."""

from datetime import datetime, timedelta

from . import config
from .bicep_curl import FIX_TEXT
from .calorie_tracker import kcal_from_met
from .equipment import label, next_load_advice

LADDER = [(3, 8), (3, 10), (3, 12)]     # (sets, reps per set) per arm
GOOD_FORM = 85.0                         # % of curls counted to move up
OK_FORM = 70.0                           # below this: form first
SEC_PER_REP = 3.0                        # slow-moderate tempo: about 1 s up, 2 s down
REST_S = 60.0                            # between sets (1-2 min recommended; lower end used)
WEEKLY_SESSIONS = 2                      # WHO 2020: at least 2 days a week

SOURCES = [
    "Sets, reps, rest and adding weight - American College of Sports Medicine (2009). Position stand: Progression "
    "models in resistance training for healthy adults. Med Sci Sports Exerc 41(3):687-708, "
    "doi:10.1249/MSS.0b013e3181915670. p. 691: \"one to three sets per exercise be used by novice individuals "
    "initially\"; p. 694: \"8-12 repetitions per set for one to three sets per exercise\"; p. 692: \"For assistance "
    "exercises ... a shorter rest period length of 1-2 min may suffice\"; p. 690: \"2-10% (lower percent for small "
    "muscle mass exercises ...) increase in load be applied when the individual can perform the current workload "
    "for one to two repetitions over the desired number on two consecutive training sessions\".",
    "Update - Currier et al. (2026). ACSM position stand: Resistance training prescription for muscle function, "
    "hypertrophy, and physical performance in healthy adults. Med Sci Sports Exerc 58(4):851-872, "
    "doi:10.1249/MSS.0000000000003897: \"healthy adults are advised to complete at least two sets per exercise\", "
    "\"at least twice weekly\"; and \"progression is not necessary to achieve beneficial outcomes\".",
    "Training days - Bull et al. (2020). World Health Organization 2020 guidelines on physical activity and "
    "sedentary behaviour. Br J Sports Med 54(24):1451-1462, doi:10.1136/bjsports-2020-102955. Table 4, adults: "
    "\"muscle-strengthening activities at moderate or greater intensity that involve all major muscle groups on "
    "2 or more days a week\".",
    "Calories - Herrmann et al. (2024). 2024 Adult Compendium of Physical Activities. J Sport Health Sci "
    "13(1):6-12, doi:10.1016/j.jshs.2023.10.010. Code 02054, 3.5 MET: \"Resistance (weight) training, multiple "
    "exercises, 8-15 reps at varied resistance\". Formula: \"METS to Kcal/min = multiply METS x 3.5 x body weight "
    "in kg then divide by 200\" (Compendium of Physical Activities website, Unit Conversions, "
    "https://pacompendium.com/unite-conversions/ - the paper: \"Additional equations used to convert EE values are "
    "available on the Compendium website\"). The paper notes the values do \"not reflect precise individual EE "
    "values\".",
]


def goal_for(step, weight_kg):
    sets, reps = LADDER[step]
    planned_s = 2 * sets * reps * SEC_PER_REP + (2 * sets - 1) * REST_S     # both arms, rests in between
    kcal = kcal_from_met(config.MET_BICEP_CURL, weight_kg, planned_s)
    return {"step": step, "sets": sets, "reps": reps, "reps_per_arm": sets * reps,
            "total_reps": 2 * sets * reps, "kcal": round(kcal, 1), "minutes": round(planned_s / 60.0, 1)}


def _met(s, goal):
    r, l = s.get("reps_right", 0), s.get("reps_left", 0)
    weakest = min(r, l) if (r and l) else max(r, l)
    return weakest >= goal["reps_per_arm"] and s.get("form_accuracy_pct", 0) >= GOOD_FORM


def is_goal_session(s):
    """True for a 'Follow my goal' session (and for sessions saved before the two ways existed)."""
    return (s or {}).get("mode", "goal") != "challenge"


def current_goal(history, weight_kg):
    """The goal for the next session: the one stored with the user's last session, or the starting goal."""
    for h in reversed(history or []):
        g = (h.get("plan") or {}).get("goal")
        if g:
            return g
    return goal_for(0, weight_kg)


def personal_best(history):
    """Most curls counted in one session so far (0 if none)."""
    return max((int((h.get("summary") or {}).get("reps_total", 0) or 0) for h in (history or [])), default=0)


def make_plan(s, history=None, weight_kg=None):
    """s: this session's summary. history: this user's earlier records [{'summary','plan'}] oldest first.
    Returns the plan incl. 'goal' for the next session (stored with the session, so the next one is judged
    against it)."""
    history = [h for h in (history or []) if (h.get("summary") or {}).get("attempted_total")]
    weight_kg = weight_kg or s.get("weight_kg") or config.USER_WEIGHT_KG
    current = current_goal(history, weight_kg)                        # the goal this session was aimed at
    goal_hist = [h for h in history if is_goal_session(h.get("summary"))]
    step = current.get("step", 0)
    acc = s.get("form_accuracy_pct", 0.0)
    r, l = s.get("reps_right", 0), s.get("reps_left", 0)
    eq = s.get("equipment")
    keep = f"Keep the same weight ({label(eq)})." if eq and eq.get("kind") != "none" else "Keep the same weight."
    plan = {"focus": [], "notes": [], "progress": None, "palm_warning": None, "grip_warning": None,
            "weight_warning": None, "this_goal": current, "met_goal": False, "weight": keep,
            "mode": "goal" if is_goal_session(s) else "challenge"}
    if eq and eq.get("kind") == "none":
        plan["notes"].append(next_load_advice(eq))
    best_before = personal_best(history)
    plan["best"] = max(best_before, int(s.get("reps_total", 0) or 0))

    if not is_goal_session(s):                  # challenge: the goal stays, the personal best may move
        reps = int(s.get("reps_total", 0) or 0)
        plan["headline"] = (f"New personal best: {reps} curls counted!" if reps > best_before and history else
                            f"Challenge done: {reps} curls counted (best {plan['best']})")
    elif _met(s, current):
        plan["met_goal"] = True
        if step < len(LADDER) - 1:
            step += 1
            plan["headline"] = "Goal reached! Next time: a few more reps"
        else:
            last = (goal_hist[-1].get("plan") or {}) if goal_hist else {}      # the last GOAL session
            prev_met = bool(last.get("met_goal")) and last.get("this_goal", {}).get("step") == len(LADDER) - 1
            if prev_met:
                step = 0
                plan["headline"] = "Two strong sessions in a row - time for a heavier weight"
                plan["weight"] = next_load_advice(s.get("equipment"))     # from the weight actually used
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

    for kind, _, text in hand_warnings(s):
        plan[f"{kind}_warning"] = text
    plan["rest"] = "Rest your biceps about 48 hours; aim for at least 2 sessions a week."
    return plan


def ordinal(n):
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th', 11 -> '11th', 21 -> '21st'."""
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def curls_line(s):
    """'You made 26 curls: 24 counted + 2 not counted (right arm 12 of 14, left arm 12 of 12).' - so the numbers
    on the phone page visibly add up (a user does not remember every curl; the rejected ones are counted too)."""
    att = int(s.get("attempted_total", 0) or 0)
    reps = int(s.get("reps_total", 0) or 0)
    if not att:
        return None
    text = f"You made {att} curl{'' if att == 1 else 's'}: {reps} counted + {att - reps} not counted"
    ar, al = s.get("attempted_right"), s.get("attempted_left")
    if ar is not None and al is not None:
        text += (f" (right arm {s.get('reps_right', 0)} of {ar}, left arm {s.get('reps_left', 0)} of {al})")
    return text + "."


def hand_warnings(s):
    """The phone page's hand cards for session summary `s`: [(kind, title, text)]. The hand checks judge every
    finished curl, counted or not, so the numbers are 'of your N curls' - not 'reps', which on the same page means
    the counted ones (15 Nov: '26 reps' was shown for a session of 24 counted reps and 26 curls)."""
    att = int(s.get("attempted_total", 0) or 0)
    reps = int(s.get("reps_total", 0) or 0)

    def of(n):
        if not att:
            return f"{n} curl{'' if n == 1 else 's'}"
        return f"{n} of your {att} curls" + (f" ({reps} counted + {att - reps} not counted)" if reps != att else "")

    out = []
    flags = s.get("palm_flags_right", 0) + s.get("palm_flags_left", 0)
    if flags >= config.OUTWARD_WARN_MIN:
        out.append(("palm", "Check your fist position",
                    f"The cameras think your fist was turned outward in {of(flags)}. This reading is not always "
                    "accurate, so check the pictures. Keep your fist facing your body (parallel to it): curling with "
                    "the fist turned out can strain the wrist and elbow."))
    grips = s.get("grip_flags_right", 0) + s.get("grip_flags_left", 0)
    if grips >= config.OUTWARD_WARN_MIN:
        out.append(("grip", "Check your grip",
                    f"Your hand looked open in {of(grips)}. With a bottle or dumbbell this can be a camera error - "
                    "check the pictures. Hold the weight firmly in your fist."))
    weights = s.get("weight_flags_right", 0) + s.get("weight_flags_left", 0)
    no_weight_chosen = (s.get("equipment") or {}).get("kind") == "none"    # the user said so: nothing to warn
    if config.HOLD_CHECK and weights >= config.OUTWARD_WARN_MIN and not no_weight_chosen:
        out.append(("weight", "No weight in your hand?",
                    f"No weight was seen in your hand in {of(weights)}. Curls without a weight do not train the "
                    "biceps much - hold a dumbbell or a water bottle. The camera can be wrong, so check the "
                    "pictures."))
    return out


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
