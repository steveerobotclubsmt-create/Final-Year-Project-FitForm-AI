"""Accounts, session storage and the phone app (Flask, served by the Pi over Wi-Fi).

How a user trains on a device (the Pi has no keyboard):
  1. The device screen shows a QR code with its address -> scan it with the phone.
  2. Log in (or create an account: username, password, body weight).
  3. Tap 'Train on this device' -> the device shows 'Hi <name>' and the next session is saved to that account.
  4. After the session the device logs out by itself, ready for the next person.
Accounts are stored on the device itself (logs/users.json, passwords hashed). Several devices sharing one
account list would need a central server - left as future work.

Endpoints: /  (login or dashboard), /sessions (my sessions, JSON), /sessions.csv (my sessions, CSV)."""

import csv
import io
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from datetime import date, timedelta

from . import config

FIELDS = [
    "timestamp", "user", "exercise", "reps_right", "reps_left", "reps_total",
    "attempted_total", "form_accuracy_pct", "duration_s", "calories_kcal",
    "avg_rep_speed_s", "load_kg",
]
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_VALID_S = 10 * 60       # a reset code is valid for 10 minutes ...
RESET_TRIES = 5               # ... and 5 tries
RESET_GAP_S = 60              # at most one code a minute ...
RESET_PER_HOUR = 5            # ... and 5 an hour per account


def local_ip():
    """The Pi's address on the Wi-Fi network (no data is sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "<pi-ip>"


class SessionLogger:
    def __init__(self, log_dir=config.LOG_DIR, filename=config.CSV_FILENAME):
        os.makedirs(log_dir, exist_ok=True)
        self.dir = os.path.abspath(log_dir)
        self.path = os.path.join(self.dir, filename)
        self.jsonl = os.path.join(self.dir, "sessions.jsonl")
        self.users_path = os.path.join(self.dir, "users.json")
        self.snap_dir = os.path.join(self.dir, "snaps")
        self._lock = threading.Lock()
        self._device_user, self._device_until, self._device_equipment = None, 0.0, None

    # ---------- accounts ----------
    def _users(self):
        if not os.path.exists(self.users_path):
            return {}
        with open(self.users_path, encoding="utf-8") as f:
            return json.load(f)

    def _write_users(self, users):
        tmp = self.users_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=1)
        os.replace(tmp, self.users_path)

    def register(self, name, password, weight_kg, email=None):
        from werkzeug.security import generate_password_hash
        if not USERNAME.match(name or ""):
            return "Username: 3-20 letters, numbers, . _ or -"
        if len(password or "") < 6:
            return "Password: at least 6 characters"
        if not 30 <= weight_kg <= 250:
            return "Body weight should be between 30 and 250 kg"
        email = (email or "").strip().lower()
        if email and not EMAIL.match(email):
            return "That email address does not look right"
        with self._lock:
            users = self._users()
            if name.lower() in (u.lower() for u in users):
                return "That username is taken"
            if email and any(u.get("email") == email for u in users.values()):
                return "That email is already used by another account"
            users[name] = {"pw": generate_password_hash(password, method="pbkdf2:sha256:200000"),
                           "weight": float(weight_kg), "created": time.strftime("%Y-%m-%d %H:%M:%S")}
            if email:
                users[name]["email"] = email
            self._write_users(users)
        return None

    # ---------- email and password reset ----------
    def email_of(self, name):
        return (self._users().get(name or "") or {}).get("email")

    def set_email(self, name, password, email):
        """Adds or changes the account's email (needs the current password). Returns an error text or None."""
        email = (email or "").strip().lower()
        if not self.check_login(name, password):
            return "Wrong password"
        if not EMAIL.match(email):
            return "That email address does not look right"
        with self._lock:
            users = self._users()
            if any(n != name and u.get("email") == email for n, u in users.items()):
                return "That email is already used by another account"
            users[name]["email"] = email
            self._write_users(users)
        return None

    def account_for(self, name_or_email):
        """The username for a username (exact capitals, as at login: 'STEVE' is not 'Steve') or an email address
        (any capitals), or None."""
        key = (name_or_email or "").strip()
        users = self._users()
        if key in users:
            return key
        for n, u in users.items():
            if u.get("email") and u["email"].lower() == key.lower():
                return n
        return None

    def start_reset(self, name, now=None):
        """A new 6-digit code for `name` (only its hash is stored). Returns (code, email) or (None, reason):
        no email on the account, or asked too often (one a minute, RESET_PER_HOUR an hour)."""
        from werkzeug.security import generate_password_hash
        now = now or time.time()
        with self._lock:
            users = self._users()
            u = users.get(name)
            if not u or not u.get("email"):
                return None, "no email"
            sent = [t for t in (u.get("reset") or {}).get("sent", []) if now - t < 3600]
            if sent and now - sent[-1] < RESET_GAP_S or len(sent) >= RESET_PER_HOUR:
                return None, "too often"
            code = f"{secrets.randbelow(10 ** 6):06d}"
            u["reset"] = {"hash": generate_password_hash(code, method="pbkdf2:sha256:200000"),
                          "until": now + RESET_VALID_S, "tries": 0, "sent": sent + [now]}
            self._write_users(users)
        return code, u["email"]

    def finish_reset(self, name, code, password, now=None):
        """Sets a new password if `code` is right and still valid. Returns an error text or None."""
        from werkzeug.security import check_password_hash, generate_password_hash
        now = now or time.time()
        if len(password or "") < 6:
            return "Password: at least 6 characters"
        with self._lock:
            users = self._users()
            r = (users.get(name) or {}).get("reset") or {}
            if not r.get("hash") or now > r.get("until", 0) or r.get("tries", 0) >= RESET_TRIES:
                return "That code has expired - ask for a new one"
            if not check_password_hash(r["hash"], (code or "").strip()):
                r["tries"] = r.get("tries", 0) + 1
                self._write_users(users)
                left = RESET_TRIES - r["tries"]
                return f"Wrong code ({left} tr{'y' if left == 1 else 'ies'} left)" if left else \
                    "Wrong code - ask for a new one"
            users[name]["pw"] = generate_password_hash(password, method="pbkdf2:sha256:200000")
            users[name]["reset"] = {"sent": r.get("sent", [])}        # code used up; keep the rate limit
            self._write_users(users)
        return None

    def check_login(self, name, password):
        from werkzeug.security import check_password_hash
        u = self._users().get(name or "")
        return bool(u) and check_password_hash(u["pw"], password or "")

    def find_user(self, name):
        """The stored spelling of a username, ignoring upper/lower case, or None."""
        return next((u for u in self._users() if u.lower() == (name or "").lower()), None)

    def set_password(self, name, password):
        """New password for an existing account (tools/reset_password.py - run on the device itself)."""
        from werkzeug.security import generate_password_hash
        if len(password or "") < 6:
            return "Password: at least 6 characters"
        with self._lock:
            users = self._users()
            if name not in users:
                return f"No account called {name!r}"
            users[name]["pw"] = generate_password_hash(password, method="pbkdf2:sha256:200000")
            self._write_users(users)
        return None

    def user_weight(self, name):
        u = self._users().get(name or "")
        return u["weight"] if u else config.USER_WEIGHT_KG

    def set_weight(self, name, weight_kg):
        with self._lock:
            users = self._users()
            if name in users and 30 <= weight_kg <= 250:
                users[name]["weight"] = float(weight_kg)
                self._write_users(users)
                return True
        return False

    def last_equipment(self, name):
        """What this user said they lift last time (pre-fills the question on the phone), or None."""
        return (self._users().get(name or "") or {}).get("equipment")

    def set_last_equipment(self, name, equipment):
        with self._lock:
            users = self._users()
            if name in users:
                users[name]["equipment"] = equipment
                self._write_users(users)

    # ---------- who is training on this device ----------
    def set_device_user(self, name, equipment=None):
        self._device_user, self._device_equipment = name, equipment
        self._device_until = time.time() + config.DEVICE_LOGIN_MINUTES * 60

    def device_user(self):
        if self._device_user and time.time() > self._device_until:
            self._device_user = None                  # nobody started within the time limit
        return self._device_user

    def device_equipment(self):
        """What the user on this device said they will lift (asked after 'Train on this device'), or None."""
        return self._device_equipment if self.device_user() else None

    def keep_device_user(self):
        """A session is running: do not let the login time out in the middle of it."""
        if self._device_user:
            self._device_until = time.time() + config.DEVICE_LOGIN_MINUTES * 60

    def clear_device_user(self):
        self._device_user = None

    # ---------- sessions ----------
    def _upgrade_csv(self):
        """A CSV from an older version (different columns, e.g. no 'user') is rewritten with the current
        columns, so new rows do not land under the wrong headings."""
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header == FIELDS:
                return
            rows = []
            for r in reader:
                if len(r) == len(FIELDS):            # already written with the current columns
                    rows.append(dict(zip(FIELDS, r)))
                elif header and len(r) == len(header):
                    rows.append(dict(zip(header, r)))
        tmp = self.path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k) or ("guest" if k == "user" else "") for k in FIELDS})
        os.replace(tmp, self.path)

    def save(self, summary, plan=None):
        with self._lock:
            new_file = not os.path.exists(self.path)
            if not new_file:
                self._upgrade_csv()
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                if new_file:
                    writer.writeheader()
                writer.writerow({k: summary.get(k, "") for k in FIELDS})
            with open(self.jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps({"summary": summary, "plan": plan}) + "\n")
        print(f"[LOG] Session saved for '{summary.get('user', 'guest')}' to {self.jsonl}")

    def read_all(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def history(self, user=None):
        """Detailed sessions, oldest first: [{'summary': {...}, 'plan': {...}}]; only `user`'s if given.
        Sessions without a counted rep are left out (older versions saved them; they are not sessions)."""
        from .session_summary import counts_as_session
        out = []
        if os.path.exists(self.jsonl):
            with open(self.jsonl, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not counts_as_session(rec.get("summary")):
                        continue
                    if user is None or (rec.get("summary") or {}).get("user") == user:
                        out.append(rec)
        return out


STYLE = """
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2330;--muted:#6b7280;--line:#e5e7eb;--accent:#2563eb;--accent2:#93c5fd;--good:#15803d;--warn:#b45309;--warnbg:#fff7ed}
@media (prefers-color-scheme: dark){:root{--bg:#0f1115;--card:#181b22;--ink:#e8eaf0;--muted:#9aa1ad;--line:#2a2f3a;--accent:#60a5fa;--accent2:#1e3a8a;--good:#4ade80;--warn:#fbbf24;--warnbg:#2a2113}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:640px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:4px 0}h2{font-size:17px;margin:0 0 10px}.muted{color:var(--muted);font-size:14px}
.top{display:flex;justify-content:space-between;align-items:center}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:14px 0}
.goal{border:2px solid var(--accent)}.big{font-size:26px;font-weight:700;margin:2px 0}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.tile{border:1px solid var(--line);border-radius:12px;padding:10px;text-align:center}
.tile b{display:block;font-size:21px}.tile span{font-size:12px;color:var(--muted)}
ul{margin:6px 0 0 18px;padding:0}li{margin:4px 0}
.warn{background:var(--warnbg);border-color:var(--warn)}.warn h2{color:var(--warn)}
.snaps{display:grid;gap:8px;margin-top:10px}.snaps img{width:100%;border-radius:10px}
figure{margin:0}figcaption{font-size:13px;color:var(--muted);margin-top:2px}
.bar{height:12px;background:var(--line);border-radius:6px;overflow:hidden}.bar i{display:block;height:100%;background:var(--good)}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:6px 4px;border-bottom:1px solid var(--line);text-align:right}td:first-child,th:first-child{text-align:left}
input{width:100%;padding:11px;margin:6px 0 10px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font-size:16px}
button,.btn{display:inline-block;width:100%;padding:12px;border:0;border-radius:10px;background:var(--accent);color:#fff;font-size:16px;font-weight:600;text-align:center;text-decoration:none}
.ghost{background:transparent;color:var(--accent);border:1px solid var(--line);width:auto;padding:8px 12px;font-size:14px}
.ok{color:var(--good);font-weight:600}.err{color:#dc2626;font-weight:600}
.choice{display:flex;gap:10px;align-items:center;padding:11px;border:1px solid var(--line);border-radius:10px;margin:6px 0}
.choice input{width:auto;margin:0}
svg text{fill:var(--muted);font-size:10px}a{color:var(--accent)}
details summary{cursor:pointer;color:var(--muted);font-size:14px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media (max-width:380px){.tiles{grid-template-columns:repeat(2,1fr)}}
"""

LOGIN = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>FitForm AI</title><style>{{ style|safe }}</style></head>
<body><main><h1>FitForm AI</h1><p class="muted">Log in to train on this device and see your progress.</p>
{% if msg %}<p class="err">{{ msg }}</p>{% endif %}{% if ok %}<p class="ok">{{ ok }}</p>{% endif %}
<div class="card"><h2>Log in</h2><form method="post" action="/login">
<label>Username<input name="username" autocomplete="username" required></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>
<button>Log in</button></form>
<p class="muted" style="margin-bottom:0"><a href="/forgot">Forgot password?</a></p></div>
<div class="card"><h2>New here? Create an account</h2><form method="post" action="/register">
<label>Username<input name="username" autocomplete="username" required></label>
<label>Password (6+ characters)<input name="password" type="password" autocomplete="new-password" required></label>
<label>Email - to reset your password if you forget it<input name="email" type="email" autocomplete="email" required></label>
<label>Body weight (kg) - used for the calorie estimate<input name="weight" type="number" step="0.5" min="30" max="250" value="70" required></label>
<button>Create account</button></form></div></main></body></html>"""

FORGOT = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>FitForm AI</title><style>{{ style|safe }}</style></head>
<body><main><h1>Forgot your password?</h1>
{% if msg %}<p class="err">{{ msg }}</p>{% endif %}
{% if not mail_ok %}<div class="card warn"><p>Password reset by email is not set up on this device yet. Ask the
device owner to reset it (tools/reset_password.py on the device).</p></div>
{% elif stage == "ask" %}<div class="card"><p class="muted">Enter your username or the email of your account. We will
email you a 6-digit code.</p><form method="post" action="/forgot">
<label>Username or email<input name="who" value="{{ who or '' }}" autocomplete="username" required></label>
<button>Send code</button></form></div>
{% else %}<div class="card"><p class="ok">If an account with an email matches, a 6-digit code has been sent to it.</p>
<p class="muted">It is valid for 10 minutes. Check your spam folder too.</p>
<form method="post" action="/reset"><input type="hidden" name="who" value="{{ who }}">
<label>Code from the email<input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required></label>
<label>New password (6+ characters)<input name="password" type="password" autocomplete="new-password" required></label>
<label>New password again<input name="password2" type="password" autocomplete="new-password" required></label>
<button>Set new password</button></form>
<p class="muted"><a href="/forgot?who={{ who|urlencode }}">Send a new code</a></p></div>{% endif %}
<p><a href="/">Back to log in</a></p></main></body></html>"""

EQUIP = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>FitForm AI</title><style>{{ style|safe }}</style></head>
<body><main><h1>What will you lift?</h1>
<p class="muted">So your report and your next goal use the weight you really train with.</p>
{% if msg %}<p class="err">{{ msg }}</p>{% endif %}
<form method="post" action="/start" class="card">
{% for key, name in kinds %}<label class="choice"><input type="radio" name="kind" value="{{ key }}"{% if key == kind %} checked{% endif %} onchange="unit()"> {{ name }}</label>
{% endfor %}
<label id="amount_label">How heavy is each one? <span id="unit">({{ unit_text }})</span>
<input name="amount" id="amount" type="number" step="0.05" min="0.1" max="50" value="{{ amount }}" inputmode="decimal"></label>
<p class="muted" id="water_note">Water weighs about 1 kg per litre, so a 0.5 L bottle is about 0.5 kg.</p>
<button>Start</button></form>
<p><a href="/">Back</a></p>
<script>
function unit(){var k=document.querySelector('input[name=kind]:checked'); k=k?k.value:'';
 document.getElementById('unit').textContent=k=='bottle'?'(litres of water in each bottle)':'(kg each)';
 var none=k=='none'; document.getElementById('amount_label').style.display=none?'none':'';
 document.getElementById('water_note').style.display=k=='bottle'?'':'none';}
unit();</script></main></body></html>"""

DASH = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>FitForm AI</title><style>{{ style|safe }}</style></head>
<body><main>
<div class="top"><h1>Hi {{ user }}</h1><a class="btn ghost" href="/logout">Log out</a></div>
{% if msg %}<p class="err">{{ msg }}</p>{% endif %}
<div class="card">
{% if device_user == user %}<p class="ok">This device is ready for you - stand in front of the camera and start.</p>
<p class="muted">Your session is saved to your account when you walk away.</p>
{% else %}<a class="btn" href="/start">Train on this device</a>
{% if device_user %}<p class="muted">Someone else is about to train on this device.</p>{% endif %}{% endif %}
</div>

<div class="card goal"><h2>Next session goal</h2>
<div class="big">{{ g.sets }} sets &times; {{ g.reps }} reps per arm</div>
<div class="muted">{{ g.total_reps }} reps in total &middot; about {{ g.kcal }} kcal &middot; about {{ g.minutes }} min</div>
{% if plan %}<p style="margin:10px 0 4px"><b>{{ plan.headline }}</b></p><ul><li>{{ plan.weight }}</li>
{% for f in plan.focus %}<li>{{ f }}</li>{% endfor %}{% for n in plan.notes %}<li>{{ n }}</li>{% endfor %}<li>{{ plan.rest }}</li></ul>
{% else %}<p class="muted">Starting goal for beginners. It grows as you reach it.</p>{% endif %}
</div>

<div class="card"><h2>This week</h2>
<div class="muted">{{ week }} of {{ week_target }} sessions (at least 2 days a week is recommended)</div>
<div class="bar"><i style="width:{{ [100, 100 * week / week_target]|min }}%"></i></div></div>

{% if hist %}
<div class="card"><h2>Calories per session</h2>
<svg viewBox="0 0 320 150" width="100%" role="img" aria-label="kcal per session with goal">
{% set n = hist|length %}{% set mx = [hist|map(attribute='summary.calories_kcal')|max, hist|map(attribute='goal_kcal')|max, 1]|max %}
{% set w = 300 / n %}
{% for h in hist %}{% set x = 10 + loop.index0 * w %}{% set bh = 100 * h.summary.calories_kcal / mx %}{% set gy = 115 - 100 * h.goal_kcal / mx %}
<rect x="{{ x + w * 0.15 }}" y="{{ 115 - bh }}" width="{{ w * 0.7 }}" height="{{ bh }}" rx="3" fill="var(--accent)"></rect>
<line x1="{{ x + w * 0.05 }}" x2="{{ x + w * 0.95 }}" y1="{{ gy }}" y2="{{ gy }}" stroke="var(--warn)" stroke-width="2" stroke-dasharray="4 2"></line>
<text x="{{ x + w / 2 }}" y="{{ 111 - bh }}" text-anchor="middle">{{ '%.0f'|format(h.summary.calories_kcal) }}</text>
<text x="{{ x + w / 2 }}" y="130" text-anchor="middle">{{ h.summary.timestamp[5:10] }}</text>
{% endfor %}
<rect x="10" y="140" width="10" height="6" fill="var(--accent)"></rect><text x="24" y="146">kcal burned</text>
<line x1="100" x2="116" y1="143" y2="143" stroke="var(--warn)" stroke-width="2" stroke-dasharray="4 2"></line><text x="120" y="146">goal for that session</text>
</svg></div>

{% set s = last.summary %}
<div class="card"><h2>Last session</h2><div class="muted" style="margin-bottom:8px">{{ s.timestamp }}
{% if last.plan and last.plan.met_goal %} &middot; <span class="ok">goal reached</span>{% endif %}</div>
<div class="tiles">
<div class="tile"><b>{{ s.reps_total }}</b><span>reps counted</span></div>
<div class="tile"><b>{{ '%.1f'|format(s.calories_kcal) }}</b><span>kcal burned</span></div>
<div class="tile"><b>{{ (s.duration_s // 60)|int }}:{{ '%02d'|format((s.duration_s % 60)|int) }}</b><span>active time</span></div>
<div class="tile"><b>{{ s.reps_right }} / {{ s.reps_left }}</b><span>right / left</span></div>
<div class="tile"><b>{{ '%.0f'|format(s.form_accuracy_pct) }}%</b><span>curls counted</span></div>
<div class="tile"><b>{{ '%.1f'|format(s.avg_rep_speed_s) }} s</b><span>average lift</span></div></div>
{% if curls %}<p style="margin:12px 0 0">{{ curls }}</p>{% endif %}
{% if s.equipment %}<p class="muted" style="margin:4px 0 0">Weight: {{ eqlabel(s.equipment) }}</p>{% endif %}
{% if s.not_counted %}<p class="muted" style="margin:12px 0 0">Not counted:</p><ul>
{% for why, n in s.not_counted.items() %}<li>{{ n }} &times; {{ why }}</li>{% endfor %}</ul>{% endif %}
{% if last.plan and last.plan.progress %}<p class="muted">{{ last.plan.progress }}</p>{% endif %}
</div>
{% for kind, title, text in warnings %}
<div class="card warn"><h2>{{ title }}</h2><p>{{ text }}</p>
<div class="snaps">{% for f in s.snapshots if kind in f %}<figure><img src="/snap/{{ f }}" alt="picture from the camera">
<figcaption>{{ caption(f) }}</figcaption></figure>{% endfor %}</div></div>
{% endfor %}

<div class="card"><h2>History</h2><table><tr><th>Date</th><th>Reps</th><th>Weight</th><th>Form</th><th>kcal</th><th>Goal</th></tr>
{% for h in hist|reverse %}<tr><td>{{ h.summary.timestamp[:16] }}</td><td>{{ h.summary.reps_total }}</td><td>{{ eqshort(h.summary.equipment) }}</td>
<td>{{ '%.0f'|format(h.summary.form_accuracy_pct) }}%</td><td>{{ '%.1f'|format(h.summary.calories_kcal) }}</td>
<td>{{ '&#10003;'|safe if h.plan and h.plan.met_goal else '-' }}</td></tr>{% endfor %}</table>
<p class="muted"><a href="/sessions.csv">Download my sessions (CSV)</a></p></div>

<div class="card"><h2>My report (PDF)</h2>
<p class="muted">Calories burned, reps, form, training days and what to work on - for the dates you choose.</p>
<form method="get" action="/report.pdf"><div class="two">
<label>From<input type="date" name="from" value="{{ rep_from }}" max="{{ today }}" required></label>
<label>To<input type="date" name="to" value="{{ today }}" max="{{ today }}" required></label></div>
<button>Download my report</button></form>
<p class="muted" style="margin-bottom:0">Quick: <a href="/report.pdf?days=7">last 7 days</a> &middot;
<a href="/report.pdf?days=30">last 30 days</a> &middot; <a href="/report.pdf?all=1">all my sessions</a></p></div>
{% else %}
<div class="card"><p>No sessions yet. Tap <b>Train on this device</b>, stand in front of the camera and start curling.</p></div>
{% endif %}

<div class="card"><h2>Settings</h2><form method="post" action="/weight">
<label>Body weight (kg)<input name="weight" type="number" step="0.5" min="30" max="250" value="{{ weight }}"></label>
<button class="ghost" style="width:100%">Save</button></form></div>
<div class="card"><h2>Email for password reset</h2>
{% if email %}<p class="muted">Codes go to <b>{{ email }}</b>.</p>{% else %}<p class="err">No email yet - add one, or a
forgotten password cannot be reset from the phone.</p>{% endif %}
<form method="post" action="/email"><label>Email<input name="email" type="email" value="{{ email or '' }}" required></label>
<label>Your password (to confirm it is you)<input name="password" type="password" autocomplete="current-password" required></label>
<button class="ghost" style="width:100%">Save email</button></form></div>
<div class="card"><details><summary>Where do the goals come from?</summary><ul>
{% for src in sources %}<li class="muted">{{ src }}</li>{% endfor %}
<li class="muted">Calories and goals are estimates and general guidance, not professional or medical advice.</li></ul></details></div>
</main></body></html>"""


SNAP_NAME = re.compile(r"_(right|left)_(?:palm|grip|weight)_(c?)(\d+)\.jpg$")


def snap_caption(name):
    """'..._right_weight_c3.jpg' -> 'Right arm - 3rd curl'. Pictures saved before 15 Nov end in a running picture
    number instead of the curl number ('..._right_weight_2.jpg'), so they only name the arm."""
    from .plan import ordinal
    m = SNAP_NAME.search(name or "")
    if not m:
        return ""
    arm, is_curl, n = m.groups()
    return f"{arm.capitalize()} arm" + (f" - {ordinal(n)} curl" if is_curl else "")


def create_app(logger, secret_key=None, mailer=None):
    from flask import (Flask, abort, jsonify, redirect, render_template_string, request, send_from_directory,
                       session)
    from .equipment import label as eq_label, short as eq_short
    from .plan import SOURCES, WEEKLY_SESSIONS, curls_line, goal_for, hand_warnings, week_count

    app = Flask(__name__)
    if secret_key is None:
        key_path = os.path.join(logger.dir, "secret.key")
        if not os.path.exists(key_path):
            with open(key_path, "w") as f:
                f.write(secrets.token_hex(32))
        with open(key_path) as f:
            secret_key = f.read().strip()
    app.secret_key = secret_key
    if mailer is None:
        from .mailer import Mailer
        mailer = Mailer(logger.dir)
    need = ("timestamp", "reps_total", "reps_right", "reps_left", "form_accuracy_pct", "calories_kcal",
            "duration_s", "avg_rep_speed_s")

    def me():
        u = session.get("user")
        return u if u and u in logger._users() else None

    @app.route("/")
    def index():
        user = me()
        if not user:
            return render_template_string(LOGIN, style=STYLE, msg=request.args.get("msg"), ok=request.args.get("ok"))
        weight = logger.user_weight(user)
        hist = [h for h in logger.history(user) if all(k in (h.get("summary") or {}) for k in need)]
        for h in hist:
            h["goal_kcal"] = ((h.get("plan") or {}).get("this_goal") or {}).get("kcal", 0) or 0
        last = hist[-1] if hist else None
        plan = last.get("plan") if last else None
        g = (plan or {}).get("goal") or goal_for(0, weight)
        # worked out from the session's numbers now (not the text saved with it), so older sessions read correctly
        warnings = hand_warnings(last["summary"]) if last else []
        today = date.today()
        return render_template_string(DASH, style=STYLE, user=user, weight=weight, hist=hist[-12:], last=last,
                                      plan=plan, g=g, week=week_count(hist), week_target=WEEKLY_SESSIONS,
                                      warnings=warnings, sources=SOURCES, device_user=logger.device_user(),
                                      email=logger.email_of(user),
                                      msg=request.args.get("msg"), today=today.isoformat(), caption=snap_caption,
                                      curls=curls_line(last["summary"]) if last else None, eqlabel=eq_label, eqshort=eq_short,
                                      rep_from=(today - timedelta(days=29)).isoformat())

    @app.route("/login", methods=["POST"])
    def login():
        # any login attempt ends the previous login on this phone first - otherwise a failed attempt still showed
        # the previous user's dashboard and looked like a successful login (16 Nov test with "' OR 1=1")
        session.pop("user", None)
        name = request.form.get("username", "").strip()
        if logger.check_login(name, request.form.get("password", "")):
            session["user"] = name
            return redirect("/")
        return redirect("/?msg=Wrong+username+or+password")

    @app.route("/forgot", methods=["GET", "POST"])
    def forgot():
        """Step 1: username or email -> a 6-digit code by email. The answer is the same whether or not an account
        matches, so the page cannot be used to find out who has an account."""
        if request.method == "GET":
            return render_template_string(FORGOT, style=STYLE, mail_ok=mailer.configured(), stage="ask",
                                          who=request.args.get("who", ""), msg=request.args.get("msg"))
        who = request.form.get("who", "").strip()
        name = logger.account_for(who)
        if name and mailer.configured():
            code, email = logger.start_reset(name)
            if code:
                try:
                    mailer.send(email, "Your FitForm password reset code",
                                f"Hi {name},\n\nYour code to reset your FitForm password is: {code}\n\n"
                                "It is valid for 10 minutes. If you did not ask for it, you can ignore this "
                                "email - your password stays the same.\n\nFitForm AI")
                except Exception as e:                 # network down, wrong app password, ...
                    print(f"[MAIL] could not send the reset code: {e}")
                    return render_template_string(FORGOT, style=STYLE, mail_ok=True, stage="ask", who=who,
                                                  msg="The email could not be sent - please try again later.")
        return render_template_string(FORGOT, style=STYLE, mail_ok=mailer.configured(), stage="code", who=who)

    @app.route("/reset", methods=["POST"])
    def reset():
        """Step 2: the code from the email and a new password."""
        who = request.form.get("who", "").strip()
        page = lambda msg: render_template_string(FORGOT, style=STYLE, mail_ok=mailer.configured(), stage="code",
                                                  who=who, msg=msg)
        if request.form.get("password", "") != request.form.get("password2", ""):
            return page("The two passwords are not the same")
        name = logger.account_for(who)
        err = logger.finish_reset(name, request.form.get("code"), request.form.get("password", "")) if name else \
            "That code has expired - ask for a new one"
        if err:
            return page(err)
        session.pop("user", None)
        return redirect("/?ok=Password+changed+-+log+in+with+your+new+password")

    @app.route("/email", methods=["POST"])
    def email():
        user = me()
        if user:
            err = logger.set_email(user, request.form.get("password", ""), request.form.get("email", ""))
            if err:
                return redirect("/?msg=" + err.replace(" ", "+"))
        return redirect("/")

    @app.route("/register", methods=["POST"])
    def register():
        name = request.form.get("username", "").strip()
        try:
            weight = float(request.form.get("weight", "70"))
        except ValueError:
            weight = 0
        err = logger.register(name, request.form.get("password", ""), weight, request.form.get("email"))
        if err:
            return redirect("/?msg=" + err.replace(" ", "+"))
        session["user"] = name
        return redirect("/")

    @app.route("/logout")
    def logout():
        session.pop("user", None)
        return redirect("/")

    @app.route("/start", methods=["GET", "POST"])
    def start():
        """'Train on this device': first asks what the user will lift, then claims the device for them."""
        from .equipment import KINDS, parse
        user = me()
        if not user:
            return redirect("/")
        last = logger.last_equipment(user) or {"kind": "dumbbell", "amount": 0.5}
        if request.method == "GET":
            kind = last.get("kind", "dumbbell")
            return render_template_string(EQUIP, style=STYLE, kinds=[(k, v[0]) for k, v in KINDS.items()],
                                          kind=kind, amount=f"{last.get('amount') or 0.5:g}",
                                          unit_text="litres of water in each bottle" if kind == "bottle" else "kg each",
                                          msg=request.args.get("msg"))
        if "kind" in request.form:
            eq, err = parse(request.form.get("kind"), request.form.get("amount"))
            if err:
                return redirect("/start?msg=" + err.replace(" ", "+"))
            logger.set_last_equipment(user, eq)
        else:                                        # (older page without the question): last answer, if any
            eq = logger.last_equipment(user)
        logger.set_device_user(user, eq)
        return redirect("/")

    @app.route("/weight", methods=["POST"])
    def weight():
        user = me()
        try:
            if user:
                logger.set_weight(user, float(request.form.get("weight", "0")))
        except ValueError:
            pass
        return redirect("/")

    @app.route("/snap/<path:name>")
    def snap(name):
        user = me()
        mine = {f for h in logger.history(user) for f in (h.get("summary") or {}).get("snapshots", [])} if user else set()
        if name not in mine:
            abort(404)
        return send_from_directory(logger.snap_dir, name)

    @app.route("/report.pdf")
    def report_pdf():
        """My training report for a period: ?from=YYYY-MM-DD&to=YYYY-MM-DD, ?days=N (up to today) or ?all=1."""
        from .report import make_report_in_process, period_records
        user = me()
        if not user:
            return redirect("/")
        today = date.today()
        try:
            if request.args.get("all"):
                recs = period_records(logger.history(user), date.min, date.max)
                start = date.fromisoformat(recs[0]["summary"]["timestamp"][:10]) if recs else today
                end = max(today, start)
            elif request.args.get("days"):
                days = max(1, min(3660, int(request.args["days"])))
                start, end = today - timedelta(days=days - 1), today
            else:
                start, end = date.fromisoformat(request.args["from"]), date.fromisoformat(request.args["to"])
        except (KeyError, ValueError):
            return redirect("/?msg=Choose+a+start+and+an+end+date")
        if start > end:
            return redirect("/?msg=The+start+date+must+be+before+the+end+date")
        if start.year < 2000 or (end - start).days > 3660:
            return redirect("/?msg=Choose+a+period+of+up+to+10+years")
        try:
            pdf = make_report_in_process(logger.dir, user, start, end, today=today)   # not in the camera's process
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            print(f"[REPORT] {e}")
            return redirect("/?msg=Sorry,+the+report+could+not+be+made.+Please+try+again.")
        if pdf is None:
            return redirect(f"/?msg=No+sessions+between+{start.isoformat()}+and+{end.isoformat()}")
        name = f"fitform_report_{user}_{start.isoformat()}_{end.isoformat()}.pdf"
        return pdf, 200, {"Content-Type": "application/pdf", "Content-Disposition": f'inline; filename="{name}"'}

    @app.route("/sessions")
    def sessions():
        user = me()
        return jsonify([h["summary"] for h in logger.history(user)] if user else [])

    @app.route("/sessions.csv")
    def sessions_csv():
        user = me()
        if not user:
            return redirect("/")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for h in logger.history(user):
            w.writerow({k: h["summary"].get(k, "") for k in FIELDS})
        return buf.getvalue(), 200, {"Content-Type": "text/csv",
                                     "Content-Disposition": f"attachment; filename=fitform_{user}.csv"}

    return app


def start_server(logger, host=config.FLASK_HOST, port=config.FLASK_PORT):
    """Runs Flask in a background thread so it does not block the camera loop."""
    app = create_app(logger)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True),
        daemon=True,
    )
    thread.start()
    print(f"[FLASK] Phone app: http://{local_ip()}:{port}/")
    return thread
