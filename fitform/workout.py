"""The two ways to train, chosen on the phone after 'Train on this device':

  Follow my goal     - the goal from plan.py, set by set (e.g. 3 sets of 8 per arm). When BOTH arms have done
                       the set, a rest countdown starts (REST_S, 60 s: ACSM 2009, p. 692, "1-2 min" for exercises
                       like curls - the lower end is used). The session stays open during the rest, even when
                       nobody is in view; a curl ends the rest early. After the last set the session is saved.
  Challenge yourself - as many good curls as you can; the session ends 30 s after the last curl (as before 22 Nov).
                       It does not change the goal; it can beat the personal best.

Before 22 Nov there was only the challenge way, while the goal said '3 sets, rest about 1 minute' - resting
ended the session after 30 s. Kept apart from main.py so it can be unit-tested."""

from .plan import REST_S

GOAL, CHALLENGE = "goal", "challenge"
ARMS = ("right", "left")
REST_WARN_S = 10.0          # 'Ten seconds' before the next set


class GoalWorkout:
    """Follows the sets of a goal. Call update() every frame with the counted reps of each arm; it returns the
    events of that frame (in order):
      ('arm_done', arm)        - this arm has its reps for the set; the other one has not yet
      ('set_done', set_no)     - both arms done, rest starts (not after the last set)
      ('rest_warning', next)   - REST_WARN_S left
      ('rest_over', set_no)    - rest finished (or a curl ended it early): set `set_no` starts
      ('goal_done', sets)      - all sets done
    Reps an arm does after its set is done (waiting for the other arm) do not carry into the next set."""

    def __init__(self, sets, reps, rest_s=REST_S):
        self.sets, self.reps, self.rest_s = int(sets), int(reps), float(rest_s)
        self.set_no = 1                         # set being done now (or the next one, while resting)
        self.base = {a: 0 for a in ARMS}        # counted reps when the current set started
        self.done = set()                       # arms that have their reps for the current set
        self.rest_until = None                  # resting until this time
        self._warned = False
        self.finished = False

    @property
    def resting(self):
        return self.rest_until is not None

    def in_set(self, arm, counts):
        """Reps of `arm` in the current set (0 while resting), at most the set's reps."""
        if self.resting:
            return 0
        return max(0, min(self.reps, counts.get(arm, 0) - self.base[arm]))

    def rest_left(self, now):
        return max(0.0, self.rest_until - now) if self.resting else 0.0

    def update(self, counts, now):
        if self.finished:
            return []
        out = []
        if self.resting:
            curled = any(counts.get(a, 0) > self.base[a] for a in ARMS)      # a curl ends the rest early
            if curled or now >= self.rest_until:
                self.rest_until = None
                out.append(("rest_over", self.set_no))
            else:
                if not self._warned and self.rest_until - now <= REST_WARN_S:
                    self._warned = True
                    out.append(("rest_warning", self.set_no))
                return out
        new = [a for a in ARMS if a not in self.done and counts.get(a, 0) - self.base[a] >= self.reps]
        self.done.update(new)
        if len(self.done) < len(ARMS):                  # (both in the same frame: just 'set done')
            out += [("arm_done", a) for a in new]
        if len(self.done) == len(ARMS):
            self.done = set()
            self.base = {a: counts.get(a, 0) for a in ARMS}
            if self.set_no >= self.sets:
                self.finished = True
                out.append(("goal_done", self.sets))
            else:
                out.append(("set_done", self.set_no))
                self.set_no += 1
                self.rest_until, self._warned = now + self.rest_s, False
        return out

    def sets_done(self):
        """Complete sets so far."""
        return self.sets if self.finished else self.set_no - 1

    def status_line(self, counts):
        """'Set 2 of 3   Left 8/8   Right 5/8' for the screen (left first, like the boards on the mirrored picture)."""
        if self.finished:
            return f"Goal done: {self.sets} sets of {self.reps}"
        return (f"Set {self.set_no} of {self.sets}   Left {self.in_set('left', counts)}/{self.reps}   "
                f"Right {self.in_set('right', counts)}/{self.reps}")
