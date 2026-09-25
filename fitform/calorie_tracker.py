"""Calories burned = MET x body weight (kg) x active hours.
The timer starts on the first rep so standing around before exercising is not counted."""

from . import config


class CalorieTracker:
    def __init__(self, weight_kg=config.USER_WEIGHT_KG, met=config.MET_BICEP_CURL):
        self.weight_kg = weight_kg
        self.met = met
        self.start_time = None

    def on_rep(self, now):
        if self.start_time is None:
            self.start_time = now

    def active_seconds(self, now):
        return 0.0 if self.start_time is None else max(0.0, now - self.start_time)

    def calories(self, now):
        return self.met * self.weight_kg * (self.active_seconds(now) / 3600.0)

    def reset(self):
        self.start_time = None
