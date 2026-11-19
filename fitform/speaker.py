"""Speaker for the spoken feedback: any Bluetooth speaker the user has, or another audio output, or none.

Uses the Pi's own tools (no extra Python packages):
  bluetoothctl - scan for audio devices, pair (answering a PIN request when an older speaker asks for one),
                 trust and connect;
  wpctl        - the PipeWire audio outputs ('sinks'); a connected Bluetooth speaker becomes one by itself.
The voice plays on the default output (pw-play), so choosing a speaker = making its output the default.
The choice is kept in logs/speaker.json and restored when FitForm starts (the speaker is reconnected).
'No speaker' mutes the voice; everything is still shown as text on the screen.
The touch screens for all this are in speaker_ui.py."""

import json
import os
import re
import select
import shutil
import subprocess
import threading
import time

from . import config

SETTINGS_FILE = "speaker.json"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x01|\x02|\r")
_MAC = re.compile(r"([0-9A-F]{2}(?::[0-9A-F]{2}){5})", re.I)


# ---------- reading the tools' output (kept apart so it can be tested without hardware) ----------
def parse_sinks(wpctl_status):
    """Audio outputs from `wpctl status`: [(id, name, is_default)], without PipeWire's 'Dummy Output'."""
    sinks, inside = [], False
    for line in wpctl_status.splitlines():
        if line.startswith("Video") or line.startswith("Settings"):
            break
        if "Sinks:" in line:
            inside = True
            continue
        if inside:
            m = re.match(r"^[\s│├└─]*(\*)?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:.*\])?\s*$", line)
            if not m:
                if re.search(r"[├└]─", line):         # the next block (Sources, Filters, ...) starts
                    break
                continue
            default, sid, name = m.group(1) == "*", int(m.group(2)), m.group(3).strip()
            if name != "Dummy Output":
                sinks.append((sid, name, default))
    return sinks


def parse_devices(text):
    """[(mac, name)] from `bluetoothctl devices`; devices without a real name (just the address) are left out."""
    out = []
    for line in _ANSI.sub("", text).splitlines():
        m = re.search(r"\bDevice\s+([0-9A-F:]{17})\s+(.+?)\s*$", line, re.I)    # (may follow a prompt)
        if m and m.group(2).replace("-", ":").upper() != m.group(1).upper():
            out.append((m.group(1).upper(), m.group(2)))
    return out


def parse_info(text):
    """The parts of `bluetoothctl info <mac>` that matter here."""
    t = _ANSI.sub("", text)
    get = lambda key: (re.search(rf"^\s*{key}:\s*(.+)$", t, re.M) or [None, None])[1]
    return {"name": get("Name") or get("Alias"), "icon": get("Icon") or "",
            "paired": get("Paired") == "yes", "connected": get("Connected") == "yes",
            "audio": "Audio Sink" in t or (get("Icon") or "").startswith("audio")}


# ---------- the speaker ----------
class Speakers:
    def __init__(self, log_dir=config.LOG_DIR, run=None):
        self.path = os.path.join(os.path.abspath(log_dir), SETTINGS_FILE)
        self._run = run or self._system_run
        self.available = bool(shutil.which("bluetoothctl") and shutil.which("wpctl")) or run is not None

    # settings
    def settings(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, **s):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, self.path)

    def muted(self):
        return self.settings().get("use") == "none"

    def current(self):
        """What the voice plays on now, as text for the screen."""
        s = self.settings()
        if s.get("use") == "none":
            return "No speaker (text only)"
        for sid, name, default in self.outputs():
            if default:
                return name
        return "No speaker found"

    # audio outputs
    def outputs(self):
        return parse_sinks(self._run(["wpctl", "status"], 10))

    def use_output(self, name):
        """Makes the output called `name` the default one. Returns True if it was found."""
        for sid, n, _ in self.outputs():
            if n == name:
                self._run(["wpctl", "set-default", str(sid)], 10)
                return True
        return False

    def use_none(self):
        self._save(use="none")

    # Bluetooth
    def paired_speakers(self):
        """[(mac, name, connected)] of the Bluetooth audio devices paired with the Pi."""
        out = []
        for mac, name in parse_devices(self._run(["bluetoothctl", "devices", "Paired"], 10)):
            info = parse_info(self._run(["bluetoothctl", "info", mac], 10))
            if info["audio"]:
                out.append((mac, info["name"] or name, info["connected"]))
        return out

    def scan(self, seconds=10):
        """Bluetooth audio devices nearby that are not paired yet: [(mac, name)]. Takes `seconds`."""
        self._run(["bluetoothctl", "power", "on"], 10)
        self._run(["bluetoothctl", "--timeout", str(int(seconds)), "scan", "on"], seconds + 10)
        paired = {m for m, _, _ in self.paired_speakers()}
        found = []
        for mac, name in parse_devices(self._run(["bluetoothctl", "devices"], 10)):
            if mac in paired:
                continue
            info = parse_info(self._run(["bluetoothctl", "info", mac], 10))
            if info["audio"]:
                found.append((mac, info["name"] or name))
        return found

    def connect(self, mac, name=None, wait=10.0):
        """Connects an already paired speaker and makes it the voice's output. Returns (ok, message)."""
        out = self._run(["bluetoothctl", "connect", mac], 25)
        if "Connection successful" not in out and "already connected" not in out.lower():
            info = parse_info(self._run(["bluetoothctl", "info", mac], 10))
            if not info["connected"]:
                return False, f"Could not connect to {name or mac} - is it on and close by?"
        name = name or parse_info(self._run(["bluetoothctl", "info", mac], 10))["name"] or mac
        end = time.monotonic() + wait                   # its audio output appears a moment after connecting
        while not self.use_output(name):
            if time.monotonic() > end:
                return False, f"{name} is connected but its sound output did not appear"
            time.sleep(0.5)
        self._save(use="bluetooth", mac=mac, name=name)
        return True, f"Connected to {name}"

    def choose_output(self, name):
        """Another output (e.g. HDMI): make it the default and remember it."""
        if not self.use_output(name):
            return False, f"{name} is not available"
        self._save(use="output", name=name)
        return True, f"Sound now plays on {name}"

    def pair(self, mac, name, ask_pin, timeout=40.0):
        """Pairs, trusts and connects a new speaker. ask_pin() is called (and may block until the user typed it)
        only if the speaker asks for a PIN; it returns the PIN or None to cancel. Returns (ok, message)."""
        try:
            proc = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
        except OSError as e:
            return False, f"Bluetooth is not available ({e})"
        buf = [""]

        def send(cmd):
            proc.stdin.write((cmd + "\n").encode())
            proc.stdin.flush()

        def wait_for(patterns, secs):
            end = time.monotonic() + secs
            while time.monotonic() < end:
                r, _, _ = select.select([proc.stdout], [], [], 0.2)
                if r:
                    chunk = os.read(proc.stdout.fileno(), 4096).decode(errors="ignore")
                    if not chunk:
                        return None
                    buf[0] += _ANSI.sub("", chunk)
                for p in patterns:
                    if p in buf[0]:
                        buf[0] = buf[0][buf[0].index(p) + len(p):]
                        return p
            return None

        try:
            for cmd in ("power on", "pairable on", "agent KeyboardDisplay", "default-agent"):
                send(cmd)
            time.sleep(0.5)
            send(f"pair {mac}")
            end = time.monotonic() + timeout
            while True:
                hit = wait_for(["Pairing successful", "Failed to pair", "Enter PIN code", "(yes/no)",
                                "AlreadyExists", "not available"], max(1.0, end - time.monotonic()))
                if hit in ("Pairing successful", "AlreadyExists"):
                    break
                if hit == "Enter PIN code":
                    pin = ask_pin()
                    if pin is None:
                        return False, "Cancelled"
                    send(pin)
                elif hit == "(yes/no)":
                    send("yes")                         # 'confirm passkey' / 'authorize service'
                elif hit == "not available":
                    return False, f"{name} is no longer visible - put it in pairing mode and search again"
                else:
                    return False, f"Could not pair with {name}" + (" (wrong PIN?)" if hit else " (no answer)")
            send(f"trust {mac}")
            wait_for(["trust succeeded", "Changing"], 5)
        finally:
            try:
                send("quit")
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
        return self.connect(mac, name)

    def forget(self, mac):
        self._run(["bluetoothctl", "remove", mac], 10)
        s = self.settings()
        if s.get("mac") == mac:
            self._save(use="auto")

    def restore(self):
        """At start-up: reconnect the remembered speaker / output (in the background - it can take seconds)."""
        s = self.settings()
        if s.get("use") == "bluetooth" and s.get("mac"):
            target, args = self.connect, (s["mac"], s.get("name"))
        elif s.get("use") == "output" and s.get("name"):
            target, args = self.choose_output, (s["name"],)
        else:
            return None
        t = threading.Thread(target=lambda: print(f"[SPEAKER] {target(*args)[1]}"), daemon=True, name="speaker")
        t.start()
        return t

    @staticmethod
    def _system_run(cmd, timeout):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as e:
            out = getattr(e, "stdout", None) or ""
            return out.decode(errors="ignore") if isinstance(out, bytes) else out
