"""Calories burned, with the formula printed by the Compendium of Physical Activities:

  "METS to Kcal/min = multiply METS x 3.5 x body weight in kg then divide by 200"
  - Compendium of Physical Activities, Unit Conversions, https://pacompendium.com/unite-conversions/
    (the website of the 2024 Adult Compendium; the paper, Herrmann et al. 2024, J Sport Health Sci 13(1):6-12,
    section 2.5: "Additional equations used to convert EE values are available on the Compendium website")

so kcal = MET x 3.5 x body weight (kg) / 200 x active minutes, with MET 3.5 (code 02054, see config.py).
The timer starts on the first rep so standing around before exercising is not counted."""

from . import config


def kcal_from_met(met, weight_kg, seconds):
    """kcal for `seconds` of an activity of `met` METs: MET x 3.5 x kg / 200 per minute (Compendium)."""
    return met * 3.5 * weight_kg / 200.0 * (seconds / 60.0)


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
        return kcal_from_met(self.met, self.weight_kg, self.active_seconds(now))

    def reset(self):
        self.start_time = None
