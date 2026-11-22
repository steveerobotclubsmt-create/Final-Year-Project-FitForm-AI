"""Decides WHAT FitForm says out loud (voice.py decides when and how).

Only feedback the system can be trusted on is spoken:
  - the arm checks (upper arm pointing down, elbow still and by the side) and the tempo (too fast, too slow,
    lowered too fast, not straightened) - these catch bad reps reliably (tested 20-27 Oct);
  - the rep count, the login greeting and the end-of-session result.
The hand readings (grip, fist direction, weight in the hand, hand not visible) are NOT spoken: they can be
wrong (see README, Known limitations), so they stay advice on the phone page, with pictures.

No repeats, no clashes:
  - a fix ('Keep your elbow by your side') is said at most once per VOICE_REPEAT_SECONDS; a rep rejected for
    the same reason again in that time just says 'Not counted.';
  - a live warning that was just said makes the rejection that follows it short as well;
  - both arms finishing in the same frame become one sentence, joined from the ready-made ones (no waiting for
    a new sentence to be made); every number and rejection says which arm (22 Nov: '1', '2' alone was unclear);
  - live warnings wait until nothing else is being said, and only during the lift."""

import re
import time

from . import config
from .bicep_curl import FIX_TEXT
from .voice import COUNT, REJECT, SESSION, TIP

SPOKEN_REASONS = ("arm_tilt", "arm_forward", "elbow", "fast", "slow", "drop", "not_lowered")
LIVE_WARNINGS = (("arm_tilted", "arm_tilt"), ("arm_forward", "arm_forward"), ("elbow_swinging", "elbow"))
# a number may wait up to COUNT_TTL s (e.g. behind a 'Not counted' sentence of the other arm, ~2.5 s); a newer
# number replaces it, so only the latest is ever said. Was 1.5 s: on 22 Nov such numbers were dropped
COUNT_TTL, TIP_TTL, REJECT_TTL, SESSION_TTL = 3.0, 1.0, 4.0, 20.0
POSITION_SAY_AFTER = 1.0     # a position instruction is said once it has been the main problem this long


def _spoken_name(name):
    """'steve_01' -> 'steve 01' (the voice reads punctuation in user names oddly)."""
    return re.sub(r"[._-]+", " ", name or "").strip()


class Coach:
    def __init__(self, voice, clock=time.monotonic):
        self.voice = voice
        self.clock = clock
        self.greeted = None
        self._live_since = {}                       # (arm, reason) -> when the live fault started
        self._pos_said, self._pos_key, self._pos_since = set(), None, None   # position check before the start
        self._drift_said = set()                    # position warnings said in this session

    def phrases(self):
        """Fixed sentences, made in the background at start-up so they are said without delay."""
        out = ["Not counted."] + [f"Not counted. {FIX_TEXT[k]}." for k in SPOKEN_REASONS]
        out += [FIX_TEXT[k] for _, k in LIVE_WARNINGS]
        for arm in ("Right", "Left", "Both arms"):
            out += [f"{arm}. Not counted."] + [f"{arm}. Not counted. {FIX_TEXT[k]}." for k in SPOKEN_REASONS]
        for n in range(1, 31):
            out += [f"Right, {n}", f"Left, {n}"]
        out += ["Saved. Closing.", "Closing."]
        out += ["Right arm done. Finish the left arm.", "Left arm done. Finish the right arm.", "Ten seconds.",
                "All sets done!"]
        from .plan import LADDER, REST_S
        for n in range(1, max(s for s, _ in LADDER) + 1):
            out += [f"Set {n} done. Rest {int(REST_S)} seconds.", f"Set {n}. Start curling."]
        from .position import ADVICE
        out += [f"{a}." for a in ADVICE.values()] + ["Good position. Start curling.", "Start curling.",
                                                      "Good position. Here is how to do a bicep curl."]
        return out

    def _fix(self, key):
        """The fix sentence for `key` if it has not been said recently (and marks it as said), else None."""
        if key not in SPOKEN_REASONS or self.voice.said_recently(("fix", key), config.VOICE_REPEAT_SECONDS):
            return None
        return FIX_TEXT[key]

    def on_events(self, events, counters):
        """events: [(arm, 'counted' | 'rejected')] from this frame."""
        if not events:
            return
        rejected = [(arm, counters[arm]) for arm, ev in events if ev != "counted"]
        if rejected:                                # a rejection matters more than a number
            arm, c = rejected[0]
            fix = self._fix(c.reject_key)
            text = "Not counted." + (f" {fix}." if fix else "")
            if len(rejected) > 1:                   # both arms curled together and both rejected
                text = f"Both arms. {text}"
            else:
                text = f"{arm.capitalize()}. {text}"
            self.voice.say(text, REJECT, key=("fix", c.reject_key) if fix else None, ttl=REJECT_TTL)
            return
        if not config.VOICE_COUNT_REPS:
            return
        parts = [f"{arm.capitalize()}, {counters[arm].count}" for arm, _ in events]
        self.voice.say(", ".join(parts), COUNT, ttl=COUNT_TTL, parts=parts)

    def on_frame(self, counters, seen_arms):
        """Live warning during the lift, once the arm fault has lasted VOICE_LIVE_HOLD_SECONDS."""
        if not config.VOICE_LIVE_WARNINGS:
            return
        now = self.clock()
        for arm in ("right", "left"):
            c = counters[arm]
            d = c.last or {}
            lifting = (arm in seen_arms and c.ready and c.stage == "down" and now >= c.blocked_until
                       and d.get("elbow_angle") is not None and d["elbow_angle"] < config.REARM_ANGLE)
            for flag, key in LIVE_WARNINGS:
                k = (arm, key)
                if not (lifting and d.get(flag)):
                    self._live_since.pop(k, None)
                    continue
                since = self._live_since.setdefault(k, now)
                if now - since < config.VOICE_LIVE_HOLD_SECONDS or self.voice.busy():
                    continue
                if self._fix(key) and self.voice.say(FIX_TEXT[key], TIP, key=("fix", key), ttl=TIP_TTL):
                    self._live_since.pop(k, None)
                    return

    def on_login(self, name):
        """Someone tapped 'Train on this device'."""
        if not name or name == self.greeted:
            return
        self.greeted = name
        then = "Let's check your position." if config.POSITION_CHECK else "Hold your arms straight to start."
        self.voice.say(f"Hi {_spoken_name(name)}. {then}", SESSION, ttl=SESSION_TTL)

    def on_logout(self):
        self.greeted = None
        self._drift_said = set()

    # ---------- position check (position.py): geometry of the whole body, reliable enough to speak ----------
    def on_position(self, problem, advice):
        """Before the first rep: say each instruction once, after it has been the main problem for
        POSITION_SAY_AFTER seconds (a problem that flickers for a frame is never said)."""
        now = self.clock()
        if problem != self._pos_key:
            self._pos_key, self._pos_since = problem, now
            return
        if problem in self._pos_said or now - self._pos_since < POSITION_SAY_AFTER:
            return
        if self.voice.say(f"{advice}.", TIP, ttl=3.0):
            self._pos_said.add(problem)

    def on_position_ok(self, guide=False):
        """The position check passed; with guide=True the curl guide (demo) is shown next."""
        self.voice.say("Good position. Here is how to do a bicep curl." if guide else "Good position. Start curling.",
                       REJECT, ttl=4.0)
        self._pos_key = None

    def on_demo_done(self):
        """The curl guide shown after the position check has finished: curls count from now."""
        self.voice.say("Start curling.", REJECT, ttl=4.0)

    def on_position_reset(self):
        """Nobody there any more: the next attempt starts fresh."""
        self._pos_said, self._pos_key, self._pos_since = set(), None, None

    def on_position_drift(self, problem, advice):
        """During a session (curls still count): each instruction at most once per session."""
        if problem in self._drift_said:
            return
        if self.voice.say(f"{advice}.", TIP, ttl=3.0):
            self._drift_said.add(problem)

    def on_session_empty(self):
        """The session ended without a counted rep, so it was not saved."""
        self.voice.say("No reps were counted, so this session was not saved.", SESSION, ttl=SESSION_TTL)

    # ---------- Follow my goal: sets and rests (workout.py) ----------
    def on_workout(self, kind, value, workout):
        """kind/value: an event from GoalWorkout.update(). 'goal_done' is said with the session result."""
        if kind == "arm_done":
            other = "left" if value == "right" else "right"
            self.voice.say(f"{value.capitalize()} arm done. Finish the {other} arm.", TIP, ttl=3.0)
        elif kind == "set_done":
            self.voice.say(f"Set {value} done. Rest {int(workout.rest_s)} seconds.", SESSION, ttl=6.0)
        elif kind == "rest_warning":
            self.voice.say("Ten seconds.", TIP, ttl=3.0)
        elif kind == "rest_over":
            self.voice.say(f"Set {value}. Start curling.", SESSION, ttl=4.0)

    def on_quit(self, saved):
        """The app is closed with the X (or Q): short, so closing is not held up."""
        self.voice.say("Saved. Closing." if saved else "Closing.", SESSION, ttl=4.0)

    def on_session_end(self, summary, plan=None):
        reps = int(summary.get("reps_total", 0) or 0)
        kcal = float(summary.get("calories_kcal", 0) or 0)
        parts = ["Session saved.", f"{reps} rep{'' if reps == 1 else 's'} counted."]
        if reps:
            parts.append("Less than 1 calorie burned." if kcal < 1 else
                         f"About {round(kcal)} calorie{'' if round(kcal) == 1 else 's'} burned.")
        plan = plan or {}
        if summary.get("mode") == "goal" and summary.get("sets_done", 0) >= summary.get("goal_sets", 99):
            parts.insert(0, "All sets done!")
        if plan.get("mode") == "challenge":
            if str(plan.get("headline", "")).startswith("New personal best"):
                parts.append("New personal best!")
            self.voice.say(" ".join(parts), SESSION, ttl=SESSION_TTL)
            return
        if plan.get("met_goal"):
            parts.append("Goal reached!")
        elif summary.get("mode") == "goal" and summary.get("sets_done", 0) >= summary.get("goal_sets", 99):
            # all sets done but too many curls not counted to move up (22 Nov: 'All sets done!' with no reason)
            from .plan import GOOD_FORM
            parts.append(f"{round(summary.get('form_accuracy_pct', 0))} percent of your curls counted. "
                         f"{round(GOOD_FORM)} percent moves you up.")
        g = plan.get("goal")
        if g:
            parts.append(f"Next goal: {g['sets']} sets of {g['reps']} per arm.")
        self.voice.say(" ".join(parts), SESSION, ttl=SESSION_TTL)
