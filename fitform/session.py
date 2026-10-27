"""Decides when a workout session is over - the Pi has no keyboard, so the user just walks away
(or stops curling for a while). Kept separate from main.py so it can be unit-tested."""

from . import config


def curls_allowed(login_required, session_running, device_user):
    """Curls only count once someone has logged in on the phone and tapped 'Train on this device'.
    A session that has started keeps counting even if the login would otherwise time out."""
    return not login_required or session_running or bool(device_user)


class SessionTracker:
    def __init__(self, away_s=None, idle_s=None):
        self.away_s = config.END_AWAY_SECONDS if away_s is None else away_s
        self.idle_s = config.END_IDLE_SECONDS if idle_s is None else idle_s
        self.active = False          # True from the first finished curl until the session ends
        self.last_seen = None        # last time a person was seen
        self.last_activity = None    # last time a curl finished (counted or not)

    def update(self, now, person_seen, curl_finished):
        """Call once per frame. Returns True on the frame the session should end."""
        if person_seen:
            self.last_seen = now
        if curl_finished:
            self.active = True
            self.last_activity = now
        if not self.active:
            return False
        away = self.last_seen is None or now - self.last_seen > self.away_s
        idle = now - self.last_activity > self.idle_s
        return away or idle

    def seconds_left(self, now):
        """Seconds until the session ends by itself (for an on-screen countdown), or None."""
        if not self.active:
            return None
        away = self.away_s - (now - self.last_seen) if self.last_seen is not None else 0.0
        idle = self.idle_s - (now - self.last_activity)
        return max(0.0, min(away, idle))

    def end(self):
        self.active = False
        self.last_activity = None
