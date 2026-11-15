"""What the user lifts in a session - asked on the phone after 'Train on this device' - and the weight advice
that follows from it.

Kinds: dumbbells (kg each), water bottles (litres each; water weighs about 1 kg per litre - the bottle itself
adds a few tens of grams, which is left out), something else (kg each) or no weight.
The weight is saved with the session, shown on the phone page and in the report, and used for the advice to
add weight, which follows ACSM 2009, p. 690: "2-10% (lower percent for small muscle mass exercises, higher
percent increase for large muscle mass exercises) increase in load" - the biceps are a small muscle group, so
FitForm points to the lower end. It does not change the calories: those come from MET x body weight x time
(see plan.py), and the Compendium value already stands for training with weights."""

KINDS = {                     # key: (name on the phone, unit, kg per unit)
    "dumbbell": ("Dumbbells", "kg", 1.0),
    "bottle": ("Water bottles", "L", 1.0),        # water: about 1 kg per litre
    "other": ("Something else", "kg", 1.0),
    "none": ("No weight", None, 0.0),
}
LIMITS = {"kg": (0.1, 50.0), "L": (0.1, 5.0)}
INCREASE = (0.02, 0.10)       # ACSM 2009, p. 690: 2-10 % (lower end for small muscle groups such as the biceps)


def parse(kind, amount):
    """-> (equipment dict, None) or (None, error text). amount: text from the form (per hand)."""
    if kind not in KINDS:
        return None, "Choose what you will lift"
    name, unit, per = KINDS[kind]
    if unit is None:
        return {"kind": "none", "amount": 0.0, "unit": None, "load_kg": 0.0}, None
    try:
        value = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        return None, f"Enter the {'weight in kg' if unit == 'kg' else 'amount of water in litres'}"
    lo, hi = LIMITS[unit]
    if not lo <= value <= hi:
        return None, f"Enter between {lo:g} and {hi:g} {unit}"
    return {"kind": kind, "amount": round(value, 3), "unit": unit, "load_kg": round(value * per, 3)}, None


def label(eq):
    """'0.5 kg dumbbells', '0.5 L water bottles (about 0.5 kg)', '1.2 kg (something else)', 'no weight'."""
    if not eq:
        return "not recorded"
    kind, a = eq.get("kind"), eq.get("amount", 0)
    if kind == "dumbbell":
        return f"{a:g} kg dumbbells"
    if kind == "bottle":
        return f"{a:g} L water bottles (about {eq.get('load_kg', a):g} kg)"
    if kind == "other":
        return f"{a:g} kg (something else)"
    return "no weight"


def short(eq):
    """For tables: '0.5 kg', '0.5 L', '-'."""
    if not eq or eq.get("kind") in (None, "none"):
        return "-" if not eq else "none"
    return f"{eq['amount']:g} {eq['unit']}"


def _fmt(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def next_load_advice(eq):
    """The advice to add weight, from the weight actually used (ACSM 2009, p. 690: 2-10 %, lower for small
    muscle groups)."""
    lo, hi = INCREASE
    if not eq:                                   # not recorded (guest, or a session from before 16 Nov)
        return ("Add 2-10 % weight - the lower end, as the biceps are a small muscle - then start again at "
                "3 sets of 8.")
    if eq.get("kind") == "none":
        return "Curls without a weight do not train the biceps much: hold a light dumbbell or a water bottle."
    a = eq["amount"]
    if eq["kind"] == "bottle":
        return (f"Add 2-10 % more water - the lower end, as the biceps are a small muscle: from {_fmt(a)} L to about "
                f"{_fmt(a * (1 + lo))}-{_fmt(a * (1 + hi))} L (about {a * lo * 1000:.0f}-{a * hi * 1000:.0f} ml "
                "more), then start again at 3 sets of 8.")
    tail = " With fixed dumbbells, take the next size up." if eq["kind"] == "dumbbell" else ""
    return (f"Add 2-10 % weight - the lower end, as the biceps are a small muscle: from {_fmt(a)} kg to about "
            f"{_fmt(a * (1 + lo))}-{_fmt(a * (1 + hi))} kg, then start again at 3 sets of 8.{tail}")
