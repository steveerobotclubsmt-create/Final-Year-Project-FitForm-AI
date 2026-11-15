"""Personalised training report (PDF) for one account over a chosen period.

report_data() works out the numbers (no drawing, so it is unit-tested); render_pdf() lays them out on A4 with
ReportLab and draws the charts with Matplotlib. Used by the phone page (/report.pdf) and by
tools/make_reports.py, which makes one report for every account that trained in a period.

Calories are the same estimate as everywhere else in FitForm: MET 3.5 x body weight x active time
(2024 Adult Compendium of Physical Activities, code 02054) - an estimate, not a measurement."""

import io
from datetime import date, datetime, timedelta

from . import config
from .bicep_curl import FIX_TEXT, REASON_TEXT
from .plan import GOOD_FORM, LADDER, OK_FORM, SOURCES, WEEKLY_SESSIONS

TIME_FMT = "%Y-%m-%d %H:%M:%S"
_TEXT_TO_KEY = {v: k for k, v in REASON_TEXT.items()}
ACCENT, LIGHT, GOAL, GOOD, INK, MUTED, LINE = "#2563eb", "#93c5fd", "#b45309", "#15803d", "#1d2330", "#6b7280", "#e5e7eb"


def _when(rec):
    try:
        return datetime.strptime((rec.get("summary") or {}).get("timestamp", ""), TIME_FMT)
    except ValueError:
        return None


def period_records(history, start, end):
    """Sessions (oldest first) whose timestamp falls on a day from `start` to `end` (dates, both included).
    Sessions in which no curl was made are left out."""
    out = []
    for rec in history:
        t = _when(rec)
        s = rec.get("summary") or {}
        if t is not None and start <= t.date() <= end and s.get("attempted_total"):
            out.append(rec)
    return sorted(out, key=_when)


def _reason_counts(s):
    """Reasons curls were not counted, as keys. Older sessions only stored the text, so map it back."""
    if s.get("not_counted_keys"):
        return dict(s["not_counted_keys"])
    return {_TEXT_TO_KEY.get(text, text): n for text, n in (s.get("not_counted") or {}).items()}


def _totals(recs):
    ss = [r["summary"] for r in recs]
    reps = sum(int(s.get("reps_total", 0) or 0) for s in ss)
    att = sum(int(s.get("attempted_total", 0) or 0) for s in ss)
    return {"sessions": len(ss), "reps": reps, "attempted": att,
            "accuracy": round(100.0 * reps / att, 1) if att else None,
            "kcal": round(sum(float(s.get("calories_kcal", 0) or 0) for s in ss), 1),
            "active_s": sum(float(s.get("duration_s", 0) or 0) for s in ss),
            "days": len({_when(r).date() for r in recs})}


def _goal_text(g):
    return f"{g['sets']} x {g['reps']}" if g else "-"


def report_data(user, history, start, end, weight_kg=None, today=None):
    """Everything the report shows, for `user`'s `history` (this user's records, any order) from `start` to
    `end` (dates, both included). Returns None if the user did not train in that period."""
    recs = period_records(history, start, end)
    if not recs:
        return None
    today = today or date.today()
    length = (end - start).days + 1
    prev = period_records(history, start - timedelta(days=length), start - timedelta(days=1))
    t, p = _totals(recs), (_totals(prev) if prev else None)
    ss = [r["summary"] for r in recs]
    plans = [r.get("plan") or {} for r in recs]
    right = sum(int(s.get("reps_right", 0) or 0) for s in ss)
    left = sum(int(s.get("reps_left", 0) or 0) for s in ss)
    lift_w = sum(float(s.get("avg_rep_speed_s", 0) or 0) * int(s.get("reps_total", 0) or 0) for s in ss)
    goal_kcal = [float((pl.get("this_goal") or {}).get("kcal", 0) or 0) for pl in plans]

    sessions = []
    for r, s, pl, gk in zip(recs, ss, plans, goal_kcal):
        sessions.append({"when": _when(r), "reps_right": int(s.get("reps_right", 0) or 0),
                         "reps_left": int(s.get("reps_left", 0) or 0), "reps": int(s.get("reps_total", 0) or 0),
                         "attempted": int(s.get("attempted_total", 0) or 0),
                         "accuracy": float(s.get("form_accuracy_pct", 0) or 0),
                         "active_s": float(s.get("duration_s", 0) or 0),
                         "kcal": float(s.get("calories_kcal", 0) or 0), "goal_kcal": gk,
                         "goal": (pl.get("this_goal") or None), "met_goal": bool(pl.get("met_goal"))})

    # training days per calendar week (Monday-Sunday) that overlaps the period - WHO: at least 2 days a week
    weeks, day = [], start - timedelta(days=start.weekday())
    active_days = {x["when"].date() for x in sessions}
    while day <= end:
        w_end = day + timedelta(days=6)
        lo, hi = max(day, start), min(w_end, end)
        weeks.append({"start": day, "end": w_end, "days": sum(1 for d in active_days if lo <= d <= hi),
                      "full": lo == day and hi == w_end})
        day += timedelta(days=7)

    reasons, flags = {}, {"palm": 0, "grip": 0, "weight": 0}
    for s in ss:
        for k, n in _reason_counts(s).items():
            reasons[k] = reasons.get(k, 0) + n
        for kind in flags:
            flags[kind] += int(s.get(f"{kind}_flags_right", 0) or 0) + int(s.get(f"{kind}_flags_left", 0) or 0)

    goal_plans = [pl for pl in plans if pl.get("this_goal")]
    first_goal = goal_plans[0]["this_goal"] if goal_plans else None
    next_goal = next((pl.get("goal") for pl in reversed(plans) if pl.get("goal")), None)
    d = {
        "user": user, "start": start, "end": end, "length_days": length, "today": today,
        "weight_kg": weight_kg or ss[-1].get("weight_kg") or config.USER_WEIGHT_KG,
        "totals": t, "prev": p, "reps_right": right, "reps_left": left,
        "avg_lift_s": round(lift_w / t["reps"], 2) if t["reps"] else None,
        "goal_kcal_total": round(sum(goal_kcal), 1), "kcal_per_session": round(t["kcal"] / t["sessions"], 1),
        "best_kcal": max(sessions, key=lambda x: x["kcal"]),
        "goals_met": sum(1 for x in sessions if x["met_goal"]), "goals_judged": len(goal_plans),
        "first_goal": first_goal, "next_goal": next_goal,
        "sessions": sessions, "weeks": weeks,
        "weeks_on_target": sum(1 for w in weeks if w["full"] and w["days"] >= WEEKLY_SESSIONS),
        "full_weeks": sum(1 for w in weeks if w["full"]),
        "reasons": sorted(reasons.items(), key=lambda kv: -kv[1]), "flags": flags,
        "weight_advice": next(((pl.get("weight") or "") for pl in reversed(plans) if pl.get("weight")), ""),
    }
    d["advice"] = _advice(d)
    return d


def _advice(d):
    """A few plain-language points for the next period, most important first."""
    t, out = d["totals"], []
    per_week = t["days"] / max(1.0, d["length_days"] / 7.0)
    if d["length_days"] >= 7 and per_week < WEEKLY_SESSIONS:
        out.append(f"Train on at least {WEEKLY_SESSIONS} days a week (WHO 2020). You averaged "
                   f"{per_week:.1f} training day{'' if round(per_week, 1) == 1 else 's'} a week.")
    acc = t["accuracy"] or 0
    if acc < OK_FORM and t["attempted"] >= 5:
        out.append(f"Only {acc:.0f} % of your curls counted. Use a lighter weight until most curls count, "
                   "then build up again.")
    elif acc >= GOOD_FORM:
        out.append(f"Good form: {acc:.0f} % of your curls counted (the goal moves up from {GOOD_FORM:.0f} %).")
    for key, n in d["reasons"][:2]:
        if key in FIX_TEXT:
            out.append(f"{FIX_TEXT[key]} - {n} curl{'s' if n != 1 else ''} were not counted because of "
                       f"'{REASON_TEXT.get(key, key)}'.")
    r, l = d["reps_right"], d["reps_left"]
    if r and l and abs(r - l) >= 3 and abs(r - l) >= 0.25 * max(r, l):
        weak = "left" if l < r else "right"
        out.append(f"Your {weak} arm did fewer reps ({min(r, l)} vs {max(r, l)}). Start each session with it.")
    elif (r or l) and not (r and l):
        out.append(f"Only your {'right' if r else 'left'} arm was trained - train both arms.")
    if d["avg_lift_s"] is not None and d["avg_lift_s"] < 0.6:
        out.append("Slow down a little: about 1 second up and 2 seconds down.")
    if d["weight_advice"] and "Increase" in d["weight_advice"]:
        out.append(d["weight_advice"])
    return out


# ---------------------------------------------------------------- drawing
def _fmt_time(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else \
        f"{seconds // 60}:{seconds % 60:02d}"


def _day(d):
    return f"{d.day} {d.strftime('%b')}"


def _period_text(d):
    s, e = d["start"], d["end"]
    return f"{_day(s)} {s.year} - {_day(e)} {e.year}" if s.year != e.year else f"{_day(s)} - {_day(e)} {e.year}"


CHART_W_CM, CHART_H_CM = 17.0, 4.6


def _chart(kind, sessions, width_cm=CHART_W_CM, height_cm=CHART_H_CM):
    """PNG of one chart. Uses Matplotlib's object interface (no pyplot), which is safe in Flask's threads."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(width_cm / 2.54, height_cm / 2.54), dpi=200)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    n = len(sessions)
    x = list(range(n))
    per_day = {}
    for s in sessions:
        per_day[s["when"].date()] = per_day.get(s["when"].date(), 0) + 1
    # several sessions on one day: the time tells them apart
    labels = [_day(s["when"]) + (s["when"].strftime("\n%H:%M") if per_day[s["when"].date()] > 1 else "")
              for s in sessions]
    if kind == "kcal":
        vals = [s["kcal"] for s in sessions]
        ax.bar(x, vals, width=0.6, color=ACCENT, label="kcal burned", zorder=2)
        goals = [(i, s["goal_kcal"]) for i, s in enumerate(sessions) if s["goal_kcal"]]
        if goals:
            ax.hlines([g for _, g in goals], [i - 0.38 for i, _ in goals], [i + 0.38 for i, _ in goals],
                      colors=GOAL, linestyles="--", linewidth=1.4, label="goal for that session", zorder=3)
        if n <= 16:
            for i, v in enumerate(vals):
                ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=6.5, color=INK)
        ax.set_ylabel("kcal", fontsize=7, color=MUTED)
    elif kind == "reps":
        r = [s["reps_right"] for s in sessions]
        l_ = [s["reps_left"] for s in sessions]
        ax.bar(x, r, width=0.6, color=ACCENT, label="right arm", zorder=2)
        ax.bar(x, l_, width=0.6, bottom=r, color=LIGHT, label="left arm", zorder=2)
        goals = [(i, 2 * s["goal"]["reps_per_arm"]) for i, s in enumerate(sessions) if s.get("goal")]
        if goals:
            ax.hlines([g for _, g in goals], [i - 0.38 for i, _ in goals], [i + 0.38 for i, _ in goals],
                      colors=GOAL, linestyles="--", linewidth=1.4, label="goal (both arms)", zorder=3)
        ax.set_ylabel("reps counted", fontsize=7, color=MUTED)
    else:                                                      # form: share of curls counted
        vals = [s["accuracy"] for s in sessions]
        ax.axhspan(GOOD_FORM, 100, color=GOOD, alpha=0.08, zorder=1)
        ax.axhline(GOOD_FORM, color=GOOD, linestyle="--", linewidth=1.0, label=f"{GOOD_FORM:.0f} % = good form")
        ax.plot(x, vals, color=ACCENT, marker="o", markersize=3.5, linewidth=1.6, label="curls counted", zorder=3)
        ax.set_ylim(0, 105)
        ax.set_ylabel("% counted", fontsize=7, color=MUTED)
    step = max(1, (n + 11) // 12)                               # at most ~12 date labels
    ax.set_xticks(x[::step])
    ax.set_xticklabels(labels[::step], fontsize=6.5, color=MUTED)
    pad = max(0.0, (6 - n) / 2.0)                               # few sessions: keep the bars narrow
    ax.set_xlim(-0.6 - pad, n - 0.4 + pad)
    ax.tick_params(axis="y", labelsize=6.5, colors=MUTED)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color=LINE, linewidth=0.6, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(LINE)
    ax.legend(fontsize=6.5, frameon=False, loc="upper left", ncol=3)
    ax.margins(y=0.18)
    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    buf.seek(0)
    return buf


def render_pdf(d):
    """The report as PDF bytes."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    ink, muted, line, accent = (colors.HexColor(c) for c in (INK, MUTED, LINE, ACCENT))
    base = getSampleStyleSheet()
    st = {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=20, leading=24, textColor=ink, spaceAfter=2,
                                alignment=0),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9.5, textColor=muted, leading=13),
        "h": ParagraphStyle("h", parent=base["Heading2"], fontSize=13, leading=16, textColor=ink, spaceBefore=12,
                            spaceAfter=5),
        "p": ParagraphStyle("p", parent=base["Normal"], fontSize=9.5, leading=13.5, textColor=ink),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=7.5, leading=10, textColor=muted),
        "num": ParagraphStyle("n", parent=base["Normal"], fontSize=17, leading=20, textColor=ink, alignment=TA_CENTER,
                              fontName="Helvetica-Bold"),
        "lab": ParagraphStyle("l", parent=base["Normal"], fontSize=7.5, leading=9.5, textColor=muted,
                              alignment=TA_CENTER),
    }
    t, p = d["totals"], d["prev"]
    W = A4[0] - 3.6 * cm

    def tiles(items, cols=4):
        cells = [[Paragraph(v, st["num"]), Paragraph(k, st["lab"])] for k, v in items]
        rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
        data = []
        for row in rows:
            data.append([Table([[c[0]], [c[1]]], colWidths=[W / cols - 8]) for c in row])
        tb = Table(data, colWidths=[W / cols] * cols)
        tb.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, line), ("INNERGRID", (0, 0), (-1, -1), 0.6, line),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        return tb

    def chart(kind):
        return Image(_chart(kind, d["sessions"]), width=W, height=W * CHART_H_CM / CHART_W_CM)

    def change(now, before, unit="", digits=0):
        if before is None:
            return "-"
        diff = now - before
        return f"{'+' if diff >= 0 else ''}{diff:.{digits}f}{unit}"

    story = [Paragraph("FitForm AI - Training report", st["title"]),
             Paragraph(f"<b>{d['user']}</b> &middot; {_period_text(d)} ({d['length_days']} days) &middot; "
                       f"body weight {d['weight_kg']:.0f} kg &middot; made {_day(d['today'])} {d['today'].year}",
                       st["sub"]),
             Spacer(1, 10)]

    acc = "-" if t["accuracy"] is None else f"{t['accuracy']:.0f} %"
    story += [tiles([("sessions", str(t["sessions"])), ("training days", str(t["days"])),
                     ("reps counted", str(t["reps"])), ("curls counted", acc),
                     ("kcal burned", f"{t['kcal']:.1f}"), ("active time", _fmt_time(t["active_s"])),
                     ("average lift", "-" if d["avg_lift_s"] is None else f"{d['avg_lift_s']:.1f} s"),
                     ("goals reached", f"{d['goals_met']} of {d['goals_judged']}" if d["goals_judged"] else "-")])]

    # ---- calories
    goal_part = ""
    if d["goal_kcal_total"]:
        pct = 100.0 * t["kcal"] / d["goal_kcal_total"]
        goal_part = (f" The goals for these sessions added up to <b>{d['goal_kcal_total']:.1f} kcal</b>, so you "
                     f"reached <b>{pct:.0f} %</b> of that.")
    best = d["best_kcal"]
    story += [Paragraph("Calories burned", st["h"]),
              Paragraph(f"You burned about <b>{t['kcal']:.1f} kcal</b> in {t['sessions']} session"
                        f"{'' if t['sessions'] == 1 else 's'} - on average <b>{d['kcal_per_session']:.1f} kcal</b> "
                        f"per session.{goal_part} Your best session was {_day(best['when'])} "
                        f"({best['kcal']:.1f} kcal in {_fmt_time(best['active_s'])}).", st["p"]),
              Spacer(1, 4), chart("kcal"),
              Paragraph(f"Estimate: MET {config.MET_BICEP_CURL} x body weight x active time (from the first to the "
                        "last curl of each session). Real energy use differs from person to person.", st["small"])]

    # ---- reps and form
    r, l = d["reps_right"], d["reps_left"]
    story += [Paragraph("Reps and form", st["h"]),
              Paragraph(f"<b>{t['reps']}</b> curls counted out of {t['attempted']} made ({acc}) - right arm "
                        f"<b>{r}</b>, left arm <b>{l}</b>."
                        + (f" Average lift time {d['avg_lift_s']:.1f} s (about 1 s is ideal)."
                           if d["avg_lift_s"] else ""), st["p"]),
              Spacer(1, 4), chart("reps"), Spacer(1, 4), chart("form")]

    # ---- consistency
    rows = [["Week", "Training days", f"Target ({WEEKLY_SESSIONS}+)"]]
    for w in d["weeks"]:
        lab = f"{_day(w['start'])} - {_day(w['end'])}" + ("" if w["full"] else " (part)")
        ok = "Yes" if w["days"] >= WEEKLY_SESSIONS else ("No" if w["full"] else "-")
        rows.append([lab, str(w["days"]), ok])
    tb = Table(rows, colWidths=[W * 0.5, W * 0.25, W * 0.25])
    tb.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5), ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
                            ("TEXTCOLOR", (0, 0), (-1, -1), ink), ("LINEBELOW", (0, 0), (-1, -1), 0.5, line),
                            ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
    target = (f"You met the target in <b>{d['weeks_on_target']} of {d['full_weeks']}</b> full week"
              f"{'' if d['full_weeks'] == 1 else 's'}." if d["full_weeks"] else "")
    story += [KeepTogether([Paragraph("Training days", st["h"]),
                            Paragraph(f"The WHO recommends muscle-strengthening on at least {WEEKLY_SESSIONS} days a "
                                      f"week. {target}", st["p"]), Spacer(1, 4), tb])]

    # ---- what to work on
    work = [Paragraph("What to work on next", st["h"])]
    work += [Paragraph(f"&bull; {a}", st["p"]) for a in d["advice"]] or [Paragraph("Keep going as you are.", st["p"])]
    if d["reasons"]:
        work.append(Paragraph("Curls not counted, by reason: " + ", ".join(
            f"{REASON_TEXT.get(k, k)} {n}" for k, n in d["reasons"]) + ".", st["small"]))
    adv = [f"fist turned out {d['flags']['palm']}" if d["flags"]["palm"] else "",
           f"hand looked open {d['flags']['grip']}" if d["flags"]["grip"] else "",
           f"no weight seen {d['flags']['weight']}" if d["flags"]["weight"] else ""]
    adv = [a for a in adv if a]
    if adv:
        work.append(Paragraph("Hand checks (advice only - the camera can be wrong here, see the pictures on the "
                              "phone page): " + ", ".join(adv) + " reps.", st["small"]))
    story += [KeepTogether(work)]

    # ---- goals and the previous period
    g0, g1 = d["first_goal"], d["next_goal"]
    goal_line = (f"Goal at the start of the period: <b>{_goal_text(g0)}</b> reps per arm; next goal: "
                 f"<b>{_goal_text(g1)}</b> reps per arm (ladder {' -> '.join(_goal_text({'sets': s, 'reps': n}) for s, n in LADDER)},"
                 " then a heavier weight).") if g1 else ""
    cmp_rows = [["", "This period", "Previous period", "Change"]]
    if p:
        pa = "-" if p["accuracy"] is None else f"{p['accuracy']:.0f} %"
        cmp_rows += [["Sessions", str(t["sessions"]), str(p["sessions"]), change(t["sessions"], p["sessions"])],
                     ["Reps counted", str(t["reps"]), str(p["reps"]), change(t["reps"], p["reps"])],
                     ["kcal burned", f"{t['kcal']:.1f}", f"{p['kcal']:.1f}", change(t["kcal"], p["kcal"], digits=1)],
                     ["Curls counted", acc, pa, change(t["accuracy"] or 0, p["accuracy"], " pts")
                      if p["accuracy"] is not None else "-"]]
    prog = [Paragraph("Progress", st["h"])]
    if goal_line:
        prog.append(Paragraph(goal_line, st["p"]))
    if p:
        ct = Table(cmp_rows, colWidths=[W * 0.31, W * 0.23, W * 0.23, W * 0.23])
        ct.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                                ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (-1, -1), ink),
                                ("LINEBELOW", (0, 0), (-1, -1), 0.5, line), ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
        prog += [Spacer(1, 4), Paragraph(f"Compared with the {d['length_days']} days before:", st["p"]),
                 Spacer(1, 3), ct]
    else:
        prog.append(Paragraph(f"No sessions in the {d['length_days']} days before, so there is nothing to compare "
                              "with yet.", st["small"]))
    story += [KeepTogether(prog)]

    # ---- all sessions
    rows = [["Date", "Reps R / L", "Counted", "Active", "kcal", "Goal kcal", "Goal"]]
    for s in d["sessions"]:
        rows.append([s["when"].strftime("%a %d %b %H:%M"), f"{s['reps_right']} / {s['reps_left']}",
                     f"{s['accuracy']:.0f} %", _fmt_time(s["active_s"]), f"{s['kcal']:.1f}",
                     f"{s['goal_kcal']:.1f}" if s["goal_kcal"] else "-", "Yes" if s["met_goal"] else "-"])
    tb = Table(rows, colWidths=[W * x for x in (0.25, 0.14, 0.12, 0.12, 0.11, 0.14, 0.12)], repeatRows=1)
    tb.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                            ("TEXTCOLOR", (0, 0), (-1, -1), ink), ("LINEBELOW", (0, 0), (-1, -1), 0.5, line),
                            ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
    story += [Paragraph("All sessions", st["h"]), tb]

    story += [KeepTogether([Paragraph("Where the numbers come from", st["h"])]
                           + [Paragraph(src, st["small"]) for src in SOURCES]
                           + [Paragraph("Calories and goals are estimates and general guidance, not professional or "
                                        "medical advice. Only curls the camera judged as correct are counted.",
                                        st["small"])])]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(1.8 * cm, 1.1 * cm, f"FitForm AI - {d['user']} - {_period_text(d)}")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Page {doc.page}")
        canvas.setStrokeColor(accent)
        canvas.setLineWidth(2)
        canvas.line(1.8 * cm, A4[1] - 1.2 * cm, A4[0] - 1.8 * cm, A4[1] - 1.2 * cm)
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.7 * cm,
                            bottomMargin=1.8 * cm, title=f"FitForm AI report - {d['user']}", author="FitForm AI")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def make_report(logger, user, start, end, today=None):
    """PDF bytes of `user`'s report from `start` to `end`, or None if they did not train then."""
    d = report_data(user, logger.history(user), start, end, logger.user_weight(user), today=today)
    return render_pdf(d) if d else None
