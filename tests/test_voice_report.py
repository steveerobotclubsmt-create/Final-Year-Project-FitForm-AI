"""Tests for the spoken feedback (voice.py, coach.py) and the personalised report (report.py, /report.pdf,
tools/make_reports.py). No camera, speaker or voice model needed: speech is recorded instead of played.
Run from the project folder with:  python tests/test_voice_report.py   (or: python -m pytest -q)"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fitform import config  # noqa: E402
from fitform.coach import Coach  # noqa: E402
from fitform.plan import goal_for  # noqa: E402
from fitform.report import make_report, period_records, render_pdf, report_data  # noqa: E402
from fitform.session_logger import SessionLogger, create_app  # noqa: E402
from fitform.voice import COUNT, REJECT, SESSION, TIP, Voice  # noqa: E402

config.VOICE_COUNT_REPS = True
config.VOICE_LIVE_WARNINGS = True
config.VOICE_LIVE_HOLD_SECONDS = 0.4
config.VOICE_REPEAT_SECONDS = 20.0


# ---------- helpers ----------
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def quiet_voice(clock):
    """A Voice that records what it would say; the test takes sentences off the queue itself."""
    return Voice(synth=lambda text: text, play=lambda path: None, clock=clock, start=False)


def said(voice):
    """Speaks whatever is waiting (as the worker would) and returns it, or None."""
    item = voice.next_item()
    if item is None:
        return None
    voice.speak_now(item)
    return item.text


def counter(count=0, reject_key=None, ready=True, stage=None, elbow=170.0, **flags):
    return SimpleNamespace(count=count, reject_key=reject_key, ready=ready, stage=stage, blocked_until=0.0,
                           last={"elbow_angle": elbow, **flags})


def counters(**kw):
    return {"right": kw.get("right") or counter(), "left": kw.get("left") or counter()}


# ---------- voice: one sentence at a time ----------
def test_more_important_sentence_replaces_a_waiting_one():
    clock = Clock()
    v = quiet_voice(clock)
    assert v.say("3", COUNT, ttl=1.5)
    assert v.say("Not counted.", REJECT, ttl=4)        # replaces the waiting number
    assert not v.say("4", COUNT, ttl=1.5)              # a number does not push out a waiting rejection
    assert said(v) == "Not counted."
    assert said(v) is None


def test_newest_sentence_of_the_same_kind_wins():
    clock = Clock()
    v = quiet_voice(clock)
    v.say("3", COUNT, ttl=1.5)
    v.say("4", COUNT, ttl=1.5)
    assert said(v) == "4"                               # never an out-of-date rep number


def test_late_sentences_are_dropped():
    clock = Clock()
    v = quiet_voice(clock)
    v.say("5", COUNT, ttl=1.5)
    clock.t += 2.0
    assert said(v) is None
    v.say("Not counted.", REJECT, ttl=4)
    clock.t += 2.0                                      # waited, but still in time
    v.say("6", COUNT, ttl=1.5)                          # lower priority: dropped while the rejection waits
    assert said(v) == "Not counted."


def test_expired_waiting_sentence_does_not_block_a_less_important_one():
    clock = Clock()
    v = quiet_voice(clock)
    v.say("Not counted.", REJECT, ttl=4)
    clock.t += 5.0
    assert v.say("7", COUNT, ttl=1.5)
    assert said(v) == "7"


def test_same_key_is_not_repeated_within_its_cooldown():
    clock = Clock()
    v = quiet_voice(clock)
    assert v.say("Keep your elbow still", TIP, key="elbow", cooldown=20)
    said(v)
    clock.t += 5
    assert not v.say("Keep your elbow still", TIP, key="elbow", cooldown=20)
    clock.t += 16
    assert v.say("Keep your elbow still", TIP, key="elbow", cooldown=20)


def test_speech_never_overlaps():
    """Sentences from several threads at once are spoken strictly one after another."""
    playing, overlaps, done = [0], [0], []
    lock = threading.Lock()

    def play(path):
        with lock:
            playing[0] += 1
            overlaps[0] = max(overlaps[0], playing[0])
        time.sleep(0.02)
        with lock:
            playing[0] -= 1
            done.append(path)

    v = Voice(synth=lambda text: text, play=play)
    threads = [threading.Thread(target=lambda i=i: [v.say(f"{i}-{k}", (k % 4) + 1) or time.sleep(0.005)
                                                   for k in range(20)]) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    end = time.time() + 3
    while v.busy() and time.time() < end:
        time.sleep(0.01)
    v.close()
    assert overlaps[0] == 1 and done


def test_voice_is_silent_without_a_model_or_when_off():
    assert not Voice(enabled=False).ready
    assert not Voice(model="models/voices/no_such_voice.onnx").ready
    assert not Voice(enabled=False).say("hello", SESSION)


def test_a_broken_speaker_does_not_stop_the_app():
    def play(path):
        raise OSError("no audio device")
    v = Voice(synth=lambda text: text, play=play, start=False)
    v.say("hello", SESSION)
    v.speak_now(v.next_item())                          # no exception
    assert v.spoken == ["hello"]


# ---------- coach: what is said ----------
def test_rejection_says_the_fix_once_then_only_not_counted():
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    c.on_events([("right", "rejected")], counters(right=counter(reject_key="elbow")))
    assert said(v) == "Right. Not counted. Keep your elbow still at your side."
    clock.t += 5
    c.on_events([("right", "rejected")], counters(right=counter(reject_key="elbow")))
    assert said(v) == "Right. Not counted."
    clock.t += 21
    c.on_events([("right", "rejected")], counters(right=counter(reject_key="elbow")))
    assert said(v) == "Right. Not counted. Keep your elbow still at your side."


def test_unreliable_hand_reasons_are_never_spoken():
    for key in ("fist", "palm_dir", "hand_hidden", "no_weight", "wrist", None):
        clock = Clock()
        v = quiet_voice(clock)
        Coach(v, clock=clock).on_events([("left", "rejected")], counters(left=counter(reject_key=key)))
        assert said(v) == "Left. Not counted.", key


def test_tempo_reasons_are_spoken():
    for key, fix in (("fast", "Lift a little slower"), ("drop", "Lower the weight slowly"),
                     ("not_lowered", "Straighten your arm fully at the bottom")):
        clock = Clock()
        v = quiet_voice(clock)
        Coach(v, clock=clock).on_events([("right", "rejected")], counters(right=counter(reject_key=key)))
        assert said(v) == f"Right. Not counted. {fix}."


def test_rep_numbers_always_name_the_arm():
    """22 Nov: with one arm in use only the number was said ('1', '2') - unclear which arm counted."""
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    c.on_events([("right", "counted")], counters(right=counter(count=1)))
    assert said(v) == "Right, 1"
    clock.t += 3
    c.on_events([("left", "counted")], counters(left=counter(count=1)))
    assert said(v) == "Left, 1"
    clock.t += 3
    c.on_events([("right", "counted"), ("left", "counted")], counters(right=counter(count=2), left=counter(count=2)))
    assert said(v) == "Right, 2, Left, 2"                # one sentence, not two that clash
    clock.t += 25                                       # left arm not used for a while
    c.on_events([("right", "counted")], counters(right=counter(count=3)))
    assert said(v) == "Right, 3"


def test_both_counts_are_joined_from_ready_made_sentences(tmp_dir=None):
    """22 Nov: 'Right, 6, Left, 5' was made as a new sentence on a hot Pi, took longer than its time limit and
    was never said. The two ready-made sentences are joined instead (a WAV join, no speech synthesis)."""
    import tempfile
    import wave
    from fitform.voice import join_wavs
    d = tempfile.mkdtemp()
    paths = []
    for i, n in enumerate((1000, 3000)):
        p = os.path.join(d, f"{i}.wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(1000)
            w.writeframes(b"\x01\x00" * n)
        paths.append(p)
    out = os.path.join(d, "joined.wav")
    join_wavs(paths, out, gap=0.25, lead_in=0.5)
    with wave.open(out, "rb") as r:
        assert r.getnframes() == 500 + 1000 + 250 + 3000
    # the coach passes the ready-made parts along with the sentence
    clock = Clock()
    v = quiet_voice(clock)
    Coach(v, clock=clock).on_events([("right", "counted"), ("left", "counted")],
                                    counters(right=counter(count=6), left=counter(count=5)))
    item = v.next_item()
    assert item.text == "Right, 6, Left, 5" and item.parts == ["Right, 6", "Left, 5"]


def test_a_number_waits_behind_the_other_arms_rejection():
    """22 Nov: 'Right, 15' came while 'Left. Not counted. Lower the weight slowly.' (~2.5 s) was being said and
    was dropped after 1.5 s. It may now wait up to 3 s."""
    clock = Clock()
    v = quiet_voice(clock)
    Coach(v, clock=clock).on_events([("right", "counted")], counters(right=counter(count=15)))
    clock.t += 2.5
    assert said(v) == "Right, 15"


def test_rejection_wins_over_a_count_in_the_same_frame():
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    c.on_events([("right", "counted"), ("left", "rejected")],
                counters(right=counter(count=4), left=counter(reject_key="fast")))
    assert said(v) == "Left. Not counted. Lift a little slower."


def test_both_arms_rejected_together_is_one_sentence():
    clock = Clock()
    v = quiet_voice(clock)
    Coach(v, clock=clock).on_events([("right", "rejected"), ("left", "rejected")],
                                    counters(right=counter(reject_key="drop"), left=counter(reject_key="drop")))
    assert said(v) == "Both arms. Not counted. Lower the weight slowly."


def test_rep_count_can_be_switched_off():
    clock = Clock()
    v = quiet_voice(clock)
    config.VOICE_COUNT_REPS = False
    try:
        Coach(v, clock=clock).on_events([("right", "counted")], counters(right=counter(count=1)))
        assert said(v) is None
    finally:
        config.VOICE_COUNT_REPS = True


def test_live_warning_needs_the_fault_to_last_and_is_said_once():
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    lifting = counter(stage="down", elbow=100.0, arm_tilted=True)
    cs = counters(right=lifting)
    c.on_frame(cs, ["right"])
    assert said(v) is None                              # just started: could be a blip
    clock.t += 0.5
    c.on_frame(cs, ["right"])
    assert said(v) == "Keep your upper arm pointing down"
    clock.t += 1
    c.on_frame(cs, ["right"])
    clock.t += 1
    c.on_frame(cs, ["right"])
    assert said(v) is None                              # not repeated
    # ... and the rejection that follows does not say the same fix again
    c.on_events([("right", "rejected")], counters(right=counter(reject_key="arm_tilt")))
    assert said(v) == "Right. Not counted."


def test_live_warning_only_during_the_lift_and_never_for_the_hand():
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    straight = counter(stage="down", elbow=170.0, arm_tilted=True)          # not lifting yet
    hand = counter(stage="down", elbow=100.0, hand_open=True, palm_away=True)
    not_ready = counter(ready=False, stage=None, elbow=100.0, elbow_swinging=True)
    for cs in (counters(right=straight), counters(right=hand), counters(right=not_ready)):
        for _ in range(3):
            c.on_frame(cs, ["right"])
            clock.t += 0.5
        assert said(v) is None


def test_live_warning_waits_while_something_is_being_said():
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    v.say("Right, 3", COUNT, ttl=1.5)                   # still waiting to be said
    cs = counters(right=counter(stage="down", elbow=100.0, elbow_swinging=True))
    c.on_frame(cs, ["right"])
    clock.t += 0.5
    c.on_frame(cs, ["right"])
    assert said(v) == "Right, 3"
    c.on_frame(cs, ["right"])
    assert said(v) == "Keep your elbow still at your side"


def test_greeting_once_per_login_and_session_result_with_calories():
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    c.on_login("steve_01")
    assert said(v) == "Hi steve 01. Let's check your position."
    c.on_login("steve_01")
    assert said(v) is None
    c.on_session_end({"reps_total": 24, "calories_kcal": 6.4},
                     {"met_goal": True, "goal": {"sets": 3, "reps": 10}})
    assert said(v) == ("Session saved. 24 reps counted. About 6 calories burned. Goal reached! "
                       "Next goal: 3 sets of 10 per arm.")
    c.on_logout()
    c.on_login("steve_01")
    assert said(v).startswith("Hi steve 01")
    c.on_session_end({"reps_total": 1, "calories_kcal": 0.3}, None)
    assert said(v) == "Session saved. 1 rep counted. Less than 1 calorie burned."
    c.on_session_end({"reps_total": 0, "calories_kcal": 0.0}, None)
    assert said(v) == "Session saved. 0 reps counted."


# ---------- report ----------
def rec(when, user="steve", right=10, left=8, attempted=20, kcal=5.0, active=120.0, lift=1.0, step=0, met=False,
        reasons=None, weight=80):
    s = {"timestamp": when.strftime("%Y-%m-%d %H:%M:%S"), "user": user, "exercise": "bicep_curl",
         "reps_right": right, "reps_left": left, "reps_total": right + left, "attempted_total": attempted,
         "form_accuracy_pct": round(100.0 * (right + left) / attempted, 1) if attempted else 0.0,
         "duration_s": active, "calories_kcal": kcal, "avg_rep_speed_s": lift, "weight_kg": weight,
         "not_counted_keys": reasons or {}, "palm_flags_right": 1, "grip_flags_left": 2}
    plan = {"this_goal": goal_for(step, weight), "goal": goal_for(min(step + int(met), 2), weight), "met_goal": met,
            "weight": "Keep the same weight."}
    return {"summary": s, "plan": plan}


def history():
    d = datetime(2026, 11, 2, 18, 0)                    # a Monday
    return [rec(d - timedelta(days=7), right=4, left=4, attempted=10, kcal=2.0),     # the week before
            rec(d, reasons={"fast": 2}), rec(d + timedelta(hours=2), kcal=3.0, reasons={"fast": 1, "elbow": 1}),
            rec(d + timedelta(days=3), right=12, left=12, attempted=24, kcal=7.5, met=True),
            rec(d + timedelta(days=9), attempted=0, right=0, left=0)]                 # no curls: left out


def test_period_records_pick_days_inclusive():
    h = history()
    recs = period_records(h, date(2026, 11, 2), date(2026, 11, 8))
    assert [r["summary"]["timestamp"][:10] for r in recs] == ["2026-11-02", "2026-11-02", "2026-11-05"]
    assert period_records(h, date(2026, 11, 11), date(2026, 11, 11)) == []           # 0 curls: not a session


def test_report_numbers_and_calories():
    d = report_data("steve", history(), date(2026, 11, 2), date(2026, 11, 8), 80, today=date(2026, 11, 8))
    t = d["totals"]
    assert t["sessions"] == 3 and t["days"] == 2
    assert t["reps"] == 18 + 18 + 24 and t["attempted"] == 64
    assert t["kcal"] == 15.5 and d["kcal_per_session"] == 5.2
    assert d["goal_kcal_total"] == round(3 * goal_for(0, 80)["kcal"], 1)
    assert d["best_kcal"]["kcal"] == 7.5
    assert d["reps_right"] == 32 and d["reps_left"] == 28
    assert d["goals_met"] == 1 and d["goals_judged"] == 3
    assert d["next_goal"]["step"] == 1                 # goal reached on the last session -> 3 x 10
    assert d["reasons"][0] == ("fast", 3)
    assert d["flags"] == {"palm": 3, "grip": 6, "weight": 0}
    assert d["weeks"][0]["days"] == 2 and d["weeks_on_target"] == 1 and d["full_weeks"] == 1
    p = d["prev"]                                       # 26 Oct - 1 Nov
    assert p["sessions"] == 1 and p["reps"] == 8 and p["kcal"] == 2.0
    assert any("Lift a little slower" in a for a in d["advice"])


def test_report_reads_older_sessions_without_reason_keys():
    r = rec(datetime(2026, 11, 3, 10, 0))
    r["summary"].pop("not_counted_keys")
    r["summary"]["not_counted"] = {"too fast": 2, "lowered too fast": 1}
    d = report_data("steve", [r], date(2026, 11, 1), date(2026, 11, 7), 80)
    assert dict(d["reasons"]) == {"fast": 2, "drop": 1}


def test_no_report_without_sessions_and_pdf_is_made():
    assert report_data("steve", history(), date(2026, 12, 1), date(2026, 12, 31), 80) is None
    d = report_data("steve", history(), date(2026, 10, 1), date(2026, 11, 30), 80, today=date(2026, 11, 30))
    pdf = render_pdf(d)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 20000
    one = report_data("steve", history()[:1], date(2026, 10, 26), date(2026, 10, 26), 80)
    assert render_pdf(one)[:5] == b"%PDF-"            # a single session works too


def test_report_on_the_phone_page():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        log.register("steve", "secret1", 80)
        for r in history():
            log.save(r["summary"], r["plan"])
        log.save(rec(datetime(2026, 11, 3, 9, 0), user="anna")["summary"], None)
        client = create_app(log, secret_key="test").test_client()
        assert client.get("/report.pdf?days=30").status_code == 302          # not logged in
        client.post("/login", data={"username": "steve", "password": "secret1"})
        assert "My report (PDF)" in client.get("/").get_data(as_text=True)
        r = client.get("/report.pdf?from=2026-11-02&to=2026-11-08")
        assert r.status_code == 200 and r.headers["Content-Type"] == "application/pdf"
        assert r.data[:5] == b"%PDF-" and "fitform_report_steve_2026-11-02_2026-11-08.pdf" in r.headers[
            "Content-Disposition"]
        assert client.get("/report.pdf?all=1").status_code == 200
        r = client.get("/report.pdf?from=2026-12-01&to=2026-12-31")
        assert r.status_code == 302 and "No+sessions" in r.headers["Location"]
        assert "No sessions between" in client.get(r.headers["Location"]).get_data(as_text=True)
        for q in ("?from=2026-11-08&to=2026-11-02", "?from=x&to=y", "?days=abc", "?from=0001-01-01&to=2026-11-08"):
            assert client.get("/report.pdf" + q).status_code == 302, q
        assert make_report(log, "anna", date(2026, 11, 1), date(2026, 11, 30)) is not None
        assert make_report(log, "nobody", date(2026, 11, 1), date(2026, 11, 30)) is None


def test_a_session_without_a_counted_rep_is_not_a_session():
    from fitform.session_summary import counts_as_session
    assert counts_as_session({"reps_total": 1}) and not counts_as_session({"reps_total": 0, "attempted_total": 3})
    assert not counts_as_session(None)
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        log.register("steve", "secret1", 80)
        empty = rec(datetime(2026, 11, 3, 9, 0), right=0, left=0, attempted=3, kcal=0.0, active=0.0)
        log.save(empty["summary"], empty["plan"])          # saved by an older version
        good = rec(datetime(2026, 11, 3, 10, 0))
        log.save(good["summary"], good["plan"])
        assert [h["summary"]["timestamp"] for h in log.history("steve")] == ["2026-11-03 10:00:00"]
        client = create_app(log, secret_key="test").test_client()
        client.post("/login", data={"username": "steve", "password": "secret1"})
        assert len(client.get("/sessions").get_json()) == 1
        assert client.get("/sessions.csv").get_data(as_text=True).count("steve") == 1
        assert report_data("steve", log.history("steve"), date(2026, 11, 3), date(2026, 11, 3), 80)["totals"][
            "sessions"] == 1
    clock = Clock()
    v = quiet_voice(clock)
    Coach(v, clock=clock).on_session_empty()
    assert said(v) == "No reps were counted, so this session was not saved."


def test_make_reports_tool_writes_one_pdf_per_active_account():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(os.path.join(tmp, "logs"))
        log.register("steve", "secret1", 80)
        log.register("anna", "secret2", 60)
        for r in history():
            log.save(r["summary"], r["plan"])               # only steve trained
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_reports.py"), "--from", "2026-11-02",
                              "--to", "2026-11-08"], cwd=tmp, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        files = os.listdir(os.path.join(tmp, "logs", "reports"))
        assert files == ["steve_2026-11-02_2026-11-08.pdf"], files
        assert "anna: no sessions" in out.stdout


# ---------- phone page: hand cards and picture captions ----------
def test_ordinals():
    from fitform.plan import ordinal
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th", "112th"]


def test_hand_cards_count_curls_not_reps():
    from fitform.plan import hand_warnings
    # the 15 Nov dumbbell session: 24 reps counted out of 26 curls, every curl flagged 'no weight'
    s = {"reps_total": 24, "attempted_total": 26, "weight_flags_right": 14, "weight_flags_left": 12,
         "palm_flags_right": 14, "palm_flags_left": 2, "grip_flags_right": 2}
    cards = {k: text for k, _, text in hand_warnings(s)}
    assert "in 26 of your 26 curls (24 counted + 2 not counted)." in cards["weight"]
    assert "in 16 of your 26 curls (24 counted + 2 not counted)." in cards["palm"]
    assert "in 2 of your 26 curls (24 counted + 2 not counted)." in cards["grip"]
    assert "in 3 of your 3 curls." in hand_warnings({"reps_total": 3, "attempted_total": 3,
                                                    "weight_flags_left": 3})[0][2]   # all counted: no '(counted)'
    assert hand_warnings({"reps_total": 3, "attempted_total": 3, "weight_flags_left": 1}) == []   # below the minimum


def test_curls_line_adds_up():
    from fitform.plan import curls_line
    s = {"reps_total": 24, "attempted_total": 26, "reps_right": 12, "reps_left": 12, "attempted_right": 14,
         "attempted_left": 12}
    assert curls_line(s) == ("You made 26 curls: 24 counted + 2 not counted "
                             "(right arm 12 of 14, left arm 12 of 12).")
    assert curls_line({"reps_total": 5, "attempted_total": 6}) == "You made 6 curls: 5 counted + 1 not counted."
    assert curls_line({"reps_total": 0, "attempted_total": 0}) is None


def test_picture_captions_name_the_arm_and_curl():
    from fitform.session_logger import snap_caption
    assert snap_caption("20261115_204150_right_weight_c3.jpg") == "Right arm - 3rd curl"
    assert snap_caption("20261115_204150_left_palm_c21.jpg") == "Left arm - 21st curl"
    assert snap_caption("20261115_204150_right_weight_2.jpg") == "Right arm"       # saved before 15 Nov
    assert snap_caption("something.jpg") == ""


def test_phone_page_shows_curl_counts_and_captions():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        log.register("steve", "secret1", 80)
        r = rec(datetime(2026, 11, 15, 20, 43), right=12, left=12, attempted=26)
        r["summary"].update(weight_flags_right=14, weight_flags_left=12,
                            snapshots=["20261115_204150_right_weight_c2.jpg", "20261115_204150_left_weight_c11.jpg"])
        r["plan"]["weight_warning"] = "No weight was seen in your hand in 26 reps."     # old text saved with it
        log.save(r["summary"], r["plan"])
        client = create_app(log, secret_key="test").test_client()
        client.post("/login", data={"username": "steve", "password": "secret1"})
        page = client.get("/").get_data(as_text=True)
        assert "in 26 of your 26 curls (24 counted + 2 not counted)" in page and "26 reps" not in page
        assert "You made 26 curls: 24 counted + 2 not counted" in page
        assert "Right arm - 2nd curl" in page and "Left arm - 11th curl" in page


# ---------- what the user lifts ----------
def test_equipment_answers_and_advice():
    from fitform.equipment import label, next_load_advice, parse, short
    eq, err = parse("dumbbell", "0.5")
    assert err is None and eq == {"kind": "dumbbell", "amount": 0.5, "unit": "kg", "load_kg": 0.5}
    assert label(eq) == "0.5 kg dumbbells" and short(eq) == "0.5 kg"
    w, _ = parse("bottle", "0,5")                                  # decimal comma from a phone keyboard
    assert w["load_kg"] == 0.5 and label(w) == "0.5 L water bottles (about 0.5 kg)"
    assert parse("none", "")[0]["load_kg"] == 0.0
    assert parse("dumbbell", "0")[1] and parse("dumbbell", "abc")[1] and parse("bottle", "9")[1]
    assert parse("anvil", "1")[1]
    # ACSM 2009 p. 690: 2-10 %, lower end for small muscles
    assert "from 0.5 kg to about 0.51-0.55 kg" in next_load_advice(eq)
    assert "next size up" in next_load_advice(eq)
    assert "from 0.5 L to about 0.51-0.55 L (about 10-50 ml more)" in next_load_advice(w)
    assert "without a weight" in next_load_advice({"kind": "none"})
    assert "Add 2-10 % weight" in next_load_advice(None)            # not recorded: general advice


def test_weight_advice_and_no_weight_warning_use_the_answer():
    from fitform.plan import goal_for, hand_warnings, make_plan
    eq = {"kind": "dumbbell", "amount": 0.5, "unit": "kg", "load_kg": 0.5}
    at12 = {"reps_right": 36, "reps_left": 36, "reps_total": 72, "attempted_total": 72, "form_accuracy_pct": 100.0,
            "equipment": eq}
    rec12 = {"summary": at12, "plan": {"goal": goal_for(2, 80)}}
    first = make_plan(at12, [rec12], 80)
    assert first["weight"] == "Keep the same weight (0.5 kg dumbbells)."
    second = make_plan(at12, [rec12, {"summary": at12, "plan": first}], 80)
    assert "from 0.5 kg to about 0.51-0.55 kg" in second["weight"]
    s = {"reps_total": 5, "attempted_total": 5, "weight_flags_right": 3, "weight_flags_left": 2}
    assert [k for k, _, _ in hand_warnings(s)] == ["weight"]
    assert hand_warnings({**s, "equipment": {"kind": "none"}}) == []   # 'no weight' was chosen: no warning


def test_challenge_keeps_the_goal_and_tracks_the_best():
    """Only 'Follow my goal' sessions move the ladder; a challenge can set a personal best."""
    from fitform.plan import current_goal, goal_for, make_plan
    big = {"reps_right": 30, "reps_left": 30, "reps_total": 60, "attempted_total": 60, "form_accuracy_pct": 100.0}
    hist = [{"summary": {**big, "reps_total": 40}, "plan": {"goal": goal_for(0, 80)}}]
    ch = make_plan({**big, "mode": "challenge"}, hist, 80)
    assert ch["mode"] == "challenge" and not ch["met_goal"] and ch["goal"]["step"] == 0
    assert ch["best"] == 60 and ch["headline"] == "New personal best: 60 curls counted!"
    gl = make_plan({**big, "mode": "goal"}, hist, 80)
    assert gl["met_goal"] and gl["goal"]["step"] == 1
    old = make_plan(big, hist, 80)                       # saved before the modes existed: a goal session
    assert old["met_goal"] and old["goal"]["step"] == 1
    assert current_goal(hist + [{"summary": big, "plan": gl}], 80)["step"] == 1
    assert current_goal([], 80)["step"] == 0
    # two goal sessions in a row at 3x12 - a challenge in between does not break the run
    at12 = {**big, "reps_right": 36, "reps_left": 36, "reps_total": 72, "mode": "goal"}
    h = [{"summary": at12, "plan": {"goal": goal_for(2, 80)}}]
    first = make_plan(at12, h, 80)
    h += [{"summary": at12, "plan": first}]
    h += [{"summary": {**big, "mode": "challenge"}, "plan": make_plan({**big, "mode": "challenge"}, h, 80)}]
    assert make_plan(at12, h, 80)["headline"].startswith("Two strong sessions in a row")


def test_phone_offers_goal_or_challenge():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        log.register("steve", "secret1", 80)
        client = create_app(log, secret_key="test").test_client()
        client.post("/login", data={"username": "steve", "password": "secret1"})
        page = client.get("/start").get_data(as_text=True)
        assert "Follow my goal: 3 sets &times; 8 per arm" in page and "Challenge yourself" in page
        assert "60 seconds of rest" in page
        client.post("/start", data={"kind": "dumbbell", "amount": "1", "mode": "goal"})
        assert log.device_user() == "steve" and log.device_mode() == "goal"
        assert "Saved after the last set" in client.get("/").get_data(as_text=True)
        client.post("/start", data={"kind": "dumbbell", "amount": "1", "mode": "challenge"})
        assert log.device_mode() == "challenge"
        log.clear_device_user()
        assert log.device_mode() == "challenge"          # nobody logged in


def test_closing_says_saved_and_closing_and_waits_for_it():
    """22 Nov: closing with the X saved the session, but the voice was switched off before anything was heard."""
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    c.on_quit(True)
    assert said(v) == "Saved. Closing."
    c.on_quit(False)
    assert said(v) == "Closing."
    assert "Saved. Closing." in c.phrases() and "Closing." in c.phrases()      # ready-made: said at once
    import threading
    import time as _t
    played = []
    live = Voice(synth=lambda text: text, play=lambda p: (_t.sleep(0.3), played.append(p)))
    live.say("Saved. Closing.", SESSION, ttl=4)
    t0 = _t.monotonic()
    live.wait_idle(3.0)
    assert played == ["Saved. Closing."] and _t.monotonic() - t0 < 2.0
    live.say("stuck", SESSION)
    live._speaking = object()                       # something that never finishes: the wait has a limit
    t0 = _t.monotonic()
    live.wait_idle(0.3)
    assert _t.monotonic() - t0 < 1.0
    live._speaking = None
    live.close()


def test_closing_cuts_a_long_sentence_short():
    """22 Nov: X tapped while the session result (~8 s) was playing - 'Closing.' never came. interrupt() stops
    the sentence being played, without the 'audio player failed' warning."""
    class FakePlayer:
        returncode = None
        def poll(self):
            return self.returncode
        def terminate(self):
            self.returncode = -15
    v = Voice(synth=lambda text: text, play=lambda p: None, start=False)
    v._player = FakePlayer()
    v.interrupt()
    assert v._player.returncode == -15 and v._interrupted
    v.interrupt()                                    # already stopped: nothing happens
    assert v._player.returncode == -15


def test_chime_before_a_sentence_after_quiet():
    """22 Nov MT speaker: after a quiet moment the first word was cut off ('...ight, 5'); a soft chime first fixed it."""
    import tempfile
    import wave
    from fitform.voice import add_chime
    d = tempfile.mkdtemp()
    src, dst = os.path.join(d, "s.wav"), os.path.join(d, "c.wav")
    with wave.open(src, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(1000)
        w.writeframes(b"\x00\x10" * 500)
    add_chime(src, dst, seconds=0.3, gap=0.12)
    with wave.open(dst) as r:
        assert r.getnframes() == 300 + 120 + 500
        frames = r.readframes(r.getnframes())
    assert frames[-1000:] == b"\x00\x10" * 500                    # the sentence itself is unchanged
    assert any(frames[i:i + 2] != b"\x00\x00" for i in range(0, 600, 2))   # a sound before it
    assert config.VOICE_CHIME and config.VOICE_CHIME_AFTER_SECONDS == 1.0


def test_sets_and_rest_are_spoken():
    from fitform.workout import GoalWorkout
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    w = GoalWorkout(3, 8)
    c.on_workout("arm_done", "right", w)
    assert said(v) == "Right arm done. Finish the left arm."
    c.on_workout("set_done", 1, w)
    assert said(v) == "Set 1 done. Rest 60 seconds."
    c.on_workout("rest_warning", 2, w)
    assert said(v) == "Ten seconds."
    c.on_workout("rest_over", 2, w)
    assert said(v) == "Set 2. Start curling."
    for line in ("Set 1 done. Rest 60 seconds.", "Set 2. Start curling.", "Right arm done. Finish the left arm."):
        assert line in c.phrases()                      # made at start-up: said without delay
    c.on_session_end({"reps_total": 48, "calories_kcal": 9.6, "mode": "goal", "sets_done": 3, "goal_sets": 3},
                     {"met_goal": True, "goal": {"sets": 3, "reps": 10}})
    assert said(v).startswith("All sets done! Session saved. 48 reps counted.")
    c.on_session_end({"reps_total": 48, "calories_kcal": 16, "mode": "goal", "sets_done": 3, "goal_sets": 3,
                      "form_accuracy_pct": 41.4}, {"met_goal": False, "goal": {"sets": 3, "reps": 8}})
    assert "41 percent of your curls counted. 50 percent moves you up. Next goal: 3 sets of 8" in said(v)
    c.on_session_end({"reps_total": 50, "calories_kcal": 9.6, "mode": "challenge"},
                     {"mode": "challenge", "headline": "New personal best: 50 curls counted!",
                      "goal": {"sets": 3, "reps": 8}})
    text = said(v)
    assert text.endswith("New personal best!") and "Next goal" not in text


def test_phone_asks_what_will_be_lifted():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        log.register("steve", "secret1", 80)
        client = create_app(log, secret_key="test").test_client()
        client.post("/login", data={"username": "steve", "password": "secret1"})
        assert 'href="/start"' in client.get("/").get_data(as_text=True)
        page = client.get("/start").get_data(as_text=True)
        assert "What will you lift?" in page and "Water bottles" in page and 'value="0.5"' in page
        r = client.post("/start", data={"kind": "bottle", "amount": "9"})
        assert r.status_code == 302 and "/start?msg=" in r.headers["Location"] and log.device_user() is None
        client.post("/start", data={"kind": "bottle", "amount": "0.6"})
        assert log.device_user() == "steve" and log.device_equipment()["amount"] == 0.6
        assert 'value="bottle" checked' in client.get("/start").get_data(as_text=True)   # remembered
        r = rec(datetime(2026, 11, 16, 10, 0))
        r["summary"]["equipment"] = log.device_equipment()
        log.save(r["summary"], r["plan"])
        page = client.get("/").get_data(as_text=True)
        assert "Weight: 0.6 L water bottles (about 0.6 kg)" in page and "<td>0.6 L</td>" in page
        d = report_data("steve", log.history("steve"), date(2026, 11, 16), date(2026, 11, 16), 80)
        assert d["weights_used"] == ["0.6 L water bottles (about 0.6 kg)"]
        assert render_pdf(d)[:5] == b"%PDF-"


# ---------- forgot password (email code) ----------
class FakeMailer:
    def __init__(self, ok=True):
        self.ok, self.sent = ok, []

    def configured(self):
        return self.ok

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))


def code_in(body):
    import re
    return re.search(r"\b(\d{6})\b", body).group(1)


def test_reset_codes_are_hashed_limited_and_expire():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        log.register("steve", "secret1", 80, "Steve@Example.com")
        log.register("anna", "secret2", 60)                          # no email
        assert log.email_of("steve") == "steve@example.com"
        assert log.register("bob", "secret3", 70, "steve@example.com") == "That email is already used by another account"
        assert log.register("bob", "secret3", 70, "not-an-email") == "That email address does not look right"
        # the username must match exactly, as at login ('STEVE' is not 'steve'); the email in any capitals
        assert log.account_for("steve") == "steve" and log.account_for("STEVE") is None
        assert log.account_for("Steve@Example.COM") == "steve" and log.account_for("nobody") is None
        assert log.start_reset("anna") == (None, "no email")
        code, to = log.start_reset("steve", now=1000.0)
        assert to == "steve@example.com" and len(code) == 6
        assert code not in open(os.path.join(tmp, "users.json")).read()          # only the hash is stored
        assert log.start_reset("steve", now=1030.0) == (None, "too often")       # one a minute
        assert log.finish_reset("steve", "000000" if code != "000000" else "111111", "newpass1", now=1040.0) \
            .startswith("Wrong code (4 tries left)")
        assert log.finish_reset("steve", code, "short", now=1040.0) == "Password: at least 6 characters"
        assert log.finish_reset("steve", code, "newpass1", now=1000.0 + 601) == "That code has expired - ask for a new one"
        code, _ = log.start_reset("steve", now=1700.0)
        assert log.finish_reset("steve", code, "newpass1", now=1710.0) is None
        assert log.check_login("steve", "newpass1") and not log.check_login("steve", "secret1")
        assert log.finish_reset("steve", code, "again123", now=1720.0) == "That code has expired - ask for a new one"
        for k in range(8):                                                        # no hourly limit,
            assert log.start_reset("steve", now=1800.0 + 70 * k)[0]               # only one a minute
        assert log.start_reset("steve", now=1800.0 + 70 * 7 + 30) == (None, "too often")
        code, _ = log.start_reset("steve", now=5000.0)
        for k in range(5):                                                        # 5 wrong tries use it up
            log.finish_reset("steve", "999999" if code != "999999" else "888888", "newpass2", now=5001.0)
        assert log.finish_reset("steve", code, "newpass2", now=5002.0) == "That code has expired - ask for a new one"
        assert log.set_email("steve", "wrong", "a@b.co") == "Wrong password"
        assert log.set_email("anna", "secret2", "anna@example.com") is None and log.email_of("anna") == "anna@example.com"


def test_forgot_password_on_the_phone():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        mail = FakeMailer()
        client = create_app(log, secret_key="test", mailer=mail).test_client()
        r = client.post("/register", data={"username": "steve", "password": "secret1", "weight": "80",
                                           "email": "steve@example.com"})
        assert r.status_code == 302 and log.email_of("steve") == "steve@example.com"
        client.get("/logout")
        assert "Forgot password?" in client.get("/").get_data(as_text=True)
        assert "Send code" in client.get("/forgot").get_data(as_text=True)
        nobody = client.post("/forgot", data={"who": "nobody"}).get_data(as_text=True)
        assert "This username or email is not registered." in nobody and not mail.sent
        caps = client.post("/forgot", data={"who": "STEVE"}).get_data(as_text=True)
        assert "is not registered" in caps and not mail.sent                        # exact capitals, as at login
        page = client.post("/forgot", data={"who": "steve@example.com"}).get_data(as_text=True)
        assert "A 6-digit code has been sent" in page and len(mail.sent) == 1
        again = client.post("/forgot", data={"who": "steve"}).get_data(as_text=True)
        assert "already sent less than a minute ago" in again and len(mail.sent) == 1   # one code a minute
        client.post("/register", data={"username": "anna", "password": "secret2", "weight": "60"})
        client.get("/logout")
        no_mail = client.post("/forgot", data={"who": "anna"}).get_data(as_text=True)
        assert "This account has no email address" in no_mail and len(mail.sent) == 1
        to, subject, body = mail.sent[0]
        assert to == "steve@example.com" and "reset" in subject.lower()
        code = code_in(body)
        bad = client.post("/reset", data={"who": "steve@example.com", "code": code, "password": "newpass1",
                                          "password2": "newpass2"}).get_data(as_text=True)
        assert "not the same" in bad
        wrong = "000000" if code != "000000" else "111111"
        assert "Wrong code" in client.post("/reset", data={"who": "steve@example.com", "code": wrong,
                                                           "password": "newpass1", "password2": "newpass1"}
                                           ).get_data(as_text=True)
        r = client.post("/reset", data={"who": "steve@example.com", "code": code, "password": "newpass1",
                                        "password2": "newpass1"})
        assert r.status_code == 302 and "Password+changed" in r.headers["Location"]
        assert "Password changed" in client.get(r.headers["Location"]).get_data(as_text=True)
        assert client.post("/login", data={"username": "steve", "password": "newpass1"}).headers["Location"] == "/"
        page = client.get("/").get_data(as_text=True)
        assert "Codes go to <b>steve@example.com</b>" in page
        # not set up on this device: the page says so instead of pretending to send
        off = create_app(log, secret_key="test", mailer=FakeMailer(ok=False)).test_client()
        assert "not set up on this device" in off.get("/forgot").get_data(as_text=True)


def test_failed_login_ends_the_previous_login_and_injection_strings_fail():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        log.register("steve", "secret1", 80)
        client = create_app(log, secret_key="test", mailer=FakeMailer()).test_client()
        client.post("/login", data={"username": "steve", "password": "secret1"})
        assert "Hi steve" in client.get("/").get_data(as_text=True)
        r = client.post("/login", data={"username": "steve", "password": "' OR 1=1 --"})
        page = client.get(r.headers["Location"]).get_data(as_text=True)
        assert "Hi steve" not in page and "Wrong username or password" in page and "Log in" in page
        for bad in ("' OR 1=1", "' OR '1'='1", "\" OR 1=1 --", "*", ""):
            for user in ("steve", bad):
                client.post("/login", data={"username": user, "password": bad})
                assert "Hi steve" not in client.get("/").get_data(as_text=True), (user, bad)


def test_email_settings_need_the_password():
    with tempfile.TemporaryDirectory() as tmp:
        log = SessionLogger(tmp)
        log.register("anna", "secret2", 60)                          # an account from before emails were asked
        client = create_app(log, secret_key="test", mailer=FakeMailer()).test_client()
        client.post("/login", data={"username": "anna", "password": "secret2"})
        assert "No email yet" in client.get("/").get_data(as_text=True)
        r = client.post("/email", data={"email": "anna@example.com", "password": "wrong"})
        assert "Wrong+password" in r.headers["Location"] and log.email_of("anna") is None
        client.post("/email", data={"email": "anna@example.com", "password": "secret2"})
        assert log.email_of("anna") == "anna@example.com"


def test_mail_settings_file_is_private():
    import stat
    from fitform.mailer import Mailer, save_settings
    with tempfile.TemporaryDirectory() as tmp:
        assert not Mailer(tmp).configured()
        path = save_settings(tmp, "fitform@example.com", "abcdabcdabcdabcd")
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and Mailer(tmp).configured()


# ---------- display: 'nobody there' screen and the drawn arm ----------
def test_nobody_there_screen_waits_for_the_grace_time():
    from fitform.session import nobody_there
    assert nobody_there(10.0, None, grace=2.0)                 # nobody seen yet
    assert not nobody_there(11.5, 10.0, grace=2.0)             # lost for 1.5 s: still the live picture
    assert nobody_there(12.0, 10.0, grace=2.0)                 # 2 s: really gone


def test_drawn_arm_is_steady_when_still_and_follows_fast_moves():
    import random
    from fitform.display_ui import ArmSmoother
    random.seed(1)
    sm = ArmSmoother()                                          # the settings in config.py
    raw, shown = [], []
    for k in range(60):                                         # arm held still, model wobbles +-6 px, 10 FPS
        p = [400 + random.uniform(-6, 6), 300 + random.uniform(-6, 6)]
        raw.append(p[0])
        shown.append(sm.update({"right": {"wrist": p}}, k * 0.1)["right"]["wrist"][0])
    spread = lambda v: max(v[20:]) - min(v[20:])
    assert spread(shown) < 0.6 * spread(raw), (spread(shown), spread(raw))
    t = 6.0
    for k in range(10):                                         # fast lift: 60 px per frame
        t += 0.1
        out = sm.update({"right": {"wrist": [400 + 60 * (k + 1), 300]}}, t)["right"]["wrist"]
    assert abs(out[0] - 1000) < 15, out                         # close behind, not lagging far
    out = sm.update({"right": {"wrist": [100, 100]}}, t + 2.0)["right"]["wrist"]
    assert out == [100, 100]                                    # arm was gone: starts fresh, no slide


# ---------- position check before the first rep ----------
def body(**change):
    """Landmarks of a person standing well: facing the camera, centred, about 2.5 m away, arms down."""
    pts = {i: [0.5, 0.5, 0.0] for i in range(33)}             # x, y, visibility (unused points unseen)
    good = {0: (0.48, 0.12), 2: (0.47, 0.10), 5: (0.50, 0.10), 11: (0.585, 0.30), 12: (0.375, 0.30),
            13: (0.62, 0.48), 14: (0.34, 0.48), 15: (0.63, 0.66), 16: (0.33, 0.66), 23: (0.56, 0.68),
            24: (0.40, 0.68)}
    for i, (x, y) in good.items():
        pts[i] = [x, y, 0.99]
    for i, val in change.items():
        pts[int(i[1:])] = val
    return [SimpleNamespace(x=x, y=y, visibility=v) for x, y, v in (pts[i] for i in range(33))]


def test_position_check_good_and_each_problem():
    from fitform.position import check_position
    r = check_position(body())
    assert r["problem"] is None and all(ok for _, ok in r["items"])
    assert check_position(None) is None
    # standing too close: hips out of the picture, shoulders wide (as in the 15 Nov recording)
    assert check_position(body(p23=[0.62, 1.08, 0.1], p24=[0.32, 1.08, 0.1]))["problem"] == "too_close"
    assert check_position(body(p11=[0.70, 0.30, 0.99], p12=[0.30, 0.30, 0.99]))["problem"] == "too_close"
    assert check_position(body(p0=[0.48, 0.12, 0.2], p2=[0.47, 0.1, 0.2]))["problem"] == "head"
    assert check_position(body(p15=[0.63, 1.02, 0.4]))["problem"] == "hands"              # hand below the picture
    far = {f"p{i}": [0.5 + 0.45 * (x - 0.5), 0.45 + 0.45 * (y - 0.45), 0.99] for i, (x, y) in   # half the size
           {0: (0.48, 0.12), 2: (0.47, 0.10), 5: (0.50, 0.10), 11: (0.585, 0.30), 12: (0.375, 0.30),
            13: (0.62, 0.48), 14: (0.34, 0.48), 15: (0.63, 0.66), 16: (0.33, 0.66), 23: (0.56, 0.68),
            24: (0.40, 0.68)}.items()}
    assert check_position(body(**far))["problem"] == "too_far"
    shift = lambda dx: {f"p{i}": [x + dx, y, 0.99] for i, (x, y) in
                        {0: (0.48, 0.12), 2: (0.47, 0.10), 5: (0.50, 0.10), 11: (0.585, 0.30), 12: (0.375, 0.30),
                         13: (0.62, 0.48), 14: (0.34, 0.48), 15: (0.63, 0.66), 16: (0.33, 0.66),
                         23: (0.56, 0.68), 24: (0.40, 0.68)}.items()}
    # picture's left = the person's own right side: they must move to their left
    assert check_position(body(**shift(-0.25)))["problem"] == "left"
    assert check_position(body(**shift(+0.25)))["problem"] == "right"
    # turned sideways: shoulders look narrow compared with the torso, at a normal distance
    assert check_position(body(p11=[0.555, 0.30, 0.99], p12=[0.43, 0.30, 0.99]))["problem"] == "turned"


def test_position_gate_needs_a_steady_good_position():
    from fitform.position import PositionGate, check_position
    good, bad = check_position(body()), check_position(body(p23=[0.62, 1.08, 0.1]))
    g = PositionGate(hold=1.0)
    assert not g.update(good, 0.0) and not g.update(good, 0.6)
    assert not g.update(bad, 0.8)                                # a bad picture starts the hold again
    assert not g.update(good, 1.0) and not g.update(good, 1.9)
    assert g.update(good, 2.0) and g.passed                      # 1 s of good position in a row
    assert not g.update(bad, 2.5) and g.passed                   # stays passed until reset
    g.reset()
    assert not g.passed and g.progress(3.0) == 0.0


def test_position_drift_warns_only_after_it_lasts():
    from fitform.position import DriftWatch, check_position
    d, bad = DriftWatch(hold=2.0), check_position(body(p15=[0.63, 1.02, 0.4]))
    assert d.update(bad, 0.0) is None and d.update(bad, 1.5) is None
    assert d.update(bad, 2.0) == "hands"
    assert d.update(check_position(body()), 2.1) is None


def test_position_instructions_are_said_once_each():
    clock = Clock()
    v = quiet_voice(clock)
    c = Coach(v, clock=clock)
    c.on_position("too_close", "Step back so your whole upper body is in view")
    assert said(v) is None                                       # just appeared: could be a blip
    clock.t += 1.1
    c.on_position("too_close", "Step back so your whole upper body is in view")
    assert said(v) == "Step back so your whole upper body is in view."
    clock.t += 5
    c.on_position("too_close", "Step back so your whole upper body is in view")
    assert said(v) is None                                       # not repeated
    c.on_position("left", "Move a little to your left")
    clock.t += 1.1
    c.on_position("left", "Move a little to your left")
    assert said(v) == "Move a little to your left."
    c.on_position_ok()
    assert said(v) == "Good position. Start curling."
    c.on_position_reset()                                        # walked away: the next attempt starts fresh
    c.on_position("left", "Move a little to your left")
    clock.t += 1.1
    c.on_position("left", "Move a little to your left")
    assert said(v) == "Move a little to your left."
    c.on_position_drift("hands", "Keep both hands in view, arms down by your sides")
    assert said(v) == "Keep both hands in view, arms down by your sides."
    c.on_position_drift("hands", "Keep both hands in view, arms down by your sides")
    assert said(v) is None                                       # once per session
    c.on_position_ok(guide=True)                                 # the curl guide is shown next ...
    assert said(v) == "Good position. Here is how to do a bicep curl."
    c.on_demo_done()                                             # ... and when it ends, curls count
    assert said(v) == "Start curling."


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("passed", name)
