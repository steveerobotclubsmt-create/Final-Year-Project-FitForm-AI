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
  - both arms finishing in the same frame become one sentence; rep numbers say which arm only while both are used;
  - live warnings wait until nothing else is being said, and only during the lift."""

import re
import time

from . import config
from .bicep_curl import FIX_TEXT
from .voice import COUNT, REJECT, SESSION, TIP

SPOKEN_REASONS = ("arm_tilt", "arm_forward", "elbow", "fast", "slow", "drop", "not_lowered")
LIVE_WARNINGS = (("arm_tilted", "arm_tilt"), ("arm_forward", "arm_forward"), ("elbow_swinging", "elbow"))
BOTH_ARMS_SECONDS = 20.0     # the other arm finished a curl this recently = both arms in use: name the arm
COUNT_TTL, TIP_TTL, REJECT_TTL, SESSION_TTL = 1.5, 1.0, 4.0, 20.0


def _spoken_name(name):
    """'steve_01' -> 'steve 01' (the voice reads punctuation in user names oddly)."""
    return re.sub(r"[._-]+", " ", name or "").strip()


class Coach:
    def __init__(self, voice, clock=time.monotonic):
        self.voice = voice
        self.clock = clock
        self.greeted = None
        self._live_since = {}                       # (arm, reason) -> when the live fault started
        self._last_event = {"right": -1e9, "left": -1e9}

    def phrases(self):
        """Fixed sentences, made in the background at start-up so they are said without delay."""
        out = ["Not counted."] + [f"Not counted. {FIX_TEXT[k]}." for k in SPOKEN_REASONS]
        out += [FIX_TEXT[k] for _, k in LIVE_WARNINGS]
        for arm in ("Right", "Left", "Both arms"):
            out += [f"{arm}. Not counted."] + [f"{arm}. Not counted. {FIX_TEXT[k]}." for k in SPOKEN_REASONS]
        for n in range(1, 31):
            out += [str(n), f"Right, {n}", f"Left, {n}"]
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
        now = self.clock()
        for arm, _ in events:
            self._last_event[arm] = now
        both = all(now - t <= BOTH_ARMS_SECONDS for t in self._last_event.values())
        rejected = [(arm, counters[arm]) for arm, ev in events if ev != "counted"]
        if rejected:                                # a rejection matters more than a number
            arm, c = rejected[0]
            fix = self._fix(c.reject_key)
            text = "Not counted." + (f" {fix}." if fix else "")
            if len(rejected) > 1:                   # both arms curled together and both rejected
                text = f"Both arms. {text}"
            elif both:
                text = f"{arm.capitalize()}. {text}"
            self.voice.say(text, REJECT, key=("fix", c.reject_key) if fix else None, ttl=REJECT_TTL)
            return
        if not config.VOICE_COUNT_REPS:
            return
        parts = [f"{arm.capitalize()}, {counters[arm].count}" if both else str(counters[arm].count)
                 for arm, _ in events]
        self.voice.say(", ".join(parts), COUNT, ttl=COUNT_TTL)

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
        self.voice.say(f"Hi {_spoken_name(name)}. Hold your arms straight to start.", SESSION, ttl=SESSION_TTL)

    def on_logout(self):
        self.greeted = None

    def on_session_empty(self):
        """The session ended without a counted rep, so it was not saved."""
        self.voice.say("No reps were counted, so this session was not saved.", SESSION, ttl=SESSION_TTL)

    def on_session_end(self, summary, plan=None):
        reps = int(summary.get("reps_total", 0) or 0)
        kcal = float(summary.get("calories_kcal", 0) or 0)
        parts = ["Session saved.", f"{reps} rep{'' if reps == 1 else 's'} counted."]
        if reps:
            parts.append("Less than 1 calorie burned." if kcal < 1 else
                         f"About {round(kcal)} calorie{'' if round(kcal) == 1 else 's'} burned.")
        plan = plan or {}
        if plan.get("met_goal"):
            parts.append("Goal reached!")
        g = plan.get("goal")
        if g:
            parts.append(f"Next goal: {g['sets']} sets of {g['reps']} per arm.")
        self.voice.say(" ".join(parts), SESSION, ttl=SESSION_TTL)
