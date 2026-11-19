"""Speaker settings on the touch screen (drawn in FitForm's window, like the X button).

  [Speaker] button (top right, next to the X; only between sessions)
    -> Speaker:  now playing on ...; your paired speakers and other outputs (tap one to use it);
                 'No speaker (text only)'; [Find new speaker] [Test sound] [Close]
    -> Searching (10 s, 'put your speaker in pairing mode') -> Found speakers (tap one to pair)
    -> PIN keypad - only if the speaker asks for a PIN (old speakers; usually 0000)
    -> Result ('Connected to ...' or why not) -> back to Speaker
Slow steps (search, pair, connect) run in a background thread so the screen keeps updating.
The backend is speaker.Speakers; a fake one with the same methods is used in the tests."""

import threading

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX
BG, PANEL, BTN, BTN_ON, TEXT, MUTED, ORANGE, GREEN, RED = (
    (20, 20, 20), (35, 35, 35), (70, 70, 70), (0, 120, 0), (240, 240, 240), (170, 170, 170), (0, 165, 255),
    (0, 200, 0), (60, 60, 220))


def _text(img, text, x, y, scale=0.6, col=TEXT, thick=2, max_w=None):
    if max_w:
        (tw, _), _ = cv2.getTextSize(text, FONT, scale, thick)
        scale = min(scale, scale * max_w / max(tw, 1))
    cv2.putText(img, text, (int(x), int(y)), FONT, scale, col, thick, cv2.LINE_AA)


class SpeakerMenu:
    BUTTON_SIZE = 56                     # same as the X button, which sits above it

    def __init__(self, speakers, voice=None):
        self.sp, self.voice = speakers, voice
        self.state = "closed"            # closed, home, busy, found, pin, result
        self.buttons = []                # [(x0, y0, x1, y1, action, label)] of the screen shown last
        self.open_rect = None            # the [Speaker] button when the menu is closed
        self.message, self.busy_text = "", ""
        self.home = None                 # (current, [(label, action)]) - loaded in the background
        self.found = []
        self.pin = ""
        self._pin_done = threading.Event()
        self._pin_value = None
        self._job = None
        if voice is not None:
            voice.muted = speakers.muted()

    # ---------- what main.py calls ----------
    @property
    def is_open(self):
        return self.state != "closed"

    def tap(self, x, y):
        """A tap at (x, y) of the shown picture. Returns True if the menu used it."""
        if self.state == "closed":
            r = self.open_rect
            if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                self.open()
                return True
            return False
        for x0, y0, x1, y1, action, _ in self.buttons:
            if x0 <= x <= x1 and y0 <= y <= y1:
                action()
                return True
        return True                      # taps on the menu's background do nothing else

    def draw(self, image, allowed=True):
        """Draws the [Speaker] button (when closed and `allowed`) or the open menu over `image`."""
        if self.state == "closed":
            self.open_rect = None
            if allowed:                                   # under the X, in the black bar beside the picture,
                h, w = image.shape[:2]                    # so the LEFT arm panel is not covered
                s = self.BUTTON_SIZE
                x0, y0 = w - 8 - s, 8 + s + 8
                self.open_rect = (x0, y0, x0 + s, y0 + s)
                cv2.rectangle(image, (x0, y0), (x0 + s, y0 + s), (60, 60, 60), -1)
                cv2.rectangle(image, (x0, y0), (x0 + s, y0 + s), (230, 230, 230), 2)
                self._speaker_icon(image, x0, y0, s)
            return image
        self.buttons = []
        h, w = image.shape[:2]
        cv2.rectangle(image, (0, 0), (w, h), BG, -1)
        getattr(self, "_draw_" + self.state)(image, w, h)
        return image

    def open(self):
        self.state = "home"
        self.home = None
        self._run(self._load_home, None)

    def close(self):
        self.state = "closed"
        self.buttons = []

    @staticmethod
    def _speaker_icon(img, x0, y0, s):
        """A loudspeaker with two sound waves, drawn in the s x s square at (x0, y0)."""
        cx, cy, white = x0 + s * 0.38, y0 + s / 2, (255, 255, 255)
        body = [(x0 + s * 0.16, cy - s * 0.10), (x0 + s * 0.30, cy - s * 0.10), (x0 + s * 0.46, cy - s * 0.24),
                (x0 + s * 0.46, cy + s * 0.24), (x0 + s * 0.30, cy + s * 0.10), (x0 + s * 0.16, cy + s * 0.10)]
        cv2.fillPoly(img, [np.array(body, np.int32)], white, cv2.LINE_AA)
        for r in (0.17, 0.30):
            cv2.ellipse(img, (int(cx + s * 0.12), int(cy)), (int(s * r), int(s * r)), 0, -40, 40, white, 2,
                        cv2.LINE_AA)

    # ---------- screens ----------
    def _button(self, img, x, y, w, h, label, action, col=BTN, scale=0.6):
        cv2.rectangle(img, (x, y), (x + w, y + h), col, -1)
        cv2.rectangle(img, (x, y), (x + w, y + h), (200, 200, 200), 1)
        (tw, th), _ = cv2.getTextSize(label, FONT, scale, 2)
        s = min(scale, scale * (w - 16) / max(tw, 1))
        (tw, th), _ = cv2.getTextSize(label, FONT, s, 2)
        _text(img, label, x + (w - tw) // 2, y + (h + th) // 2, s)
        self.buttons.append((x, y, x + w, y + h, action, label))

    def _draw_home(self, img, w, h):
        _text(img, "Speaker", 24, 44, 1.0, ORANGE)
        if self.home is None:
            _text(img, "Looking for speakers...", 24, 100, 0.7, MUTED)
        else:
            current, options = self.home
            _text(img, f"Now: {current}", 24, 84, 0.65, MUTED, max_w=w - 48)
            _text(img, "Tap where FitForm should talk:", 24, 120, 0.6)
            y = 136
            for label, action, on in options[:5]:
                self._button(img, 24, y, w - 48, 46, label, action, BTN_ON if on else BTN)
                y += 54
        bw = (w - 48 - 2 * 12) // 3
        y = h - 70
        self._button(img, 24, y, bw, 56, "Find new speaker", self._start_scan, (120, 70, 0))
        self._button(img, 24 + bw + 12, y, bw, 56, "Test sound", self._test_sound)
        self._button(img, 24 + 2 * (bw + 12), y, bw, 56, "Close", self.close)

    def _draw_busy(self, img, w, h):
        _text(img, "Speaker", 24, 44, 1.0, ORANGE)
        for i, line in enumerate(self.busy_text.split("\n")):
            _text(img, line, 24, 120 + 40 * i, 0.7, max_w=w - 48)
        _text(img, "Please wait...", 24, h - 40, 0.6, MUTED)

    def _draw_found(self, img, w, h):
        _text(img, "Speakers found", 24, 44, 1.0, ORANGE)
        if not self.found:
            _text(img, "No speaker found.", 24, 110, 0.7)
            _text(img, "Is it on and in pairing mode (Bluetooth light flashing)?", 24, 150, 0.6, MUTED, max_w=w - 48)
        else:
            _text(img, "Tap your speaker to connect it:", 24, 84, 0.6)
            y = 100
            for mac, name in self.found[:5]:
                self._button(img, 24, y, w - 48, 50, name, lambda m=mac, n=name: self._start_pair(m, n))
                y += 58
        bw = (w - 48 - 12) // 2
        self._button(img, 24, h - 70, bw, 56, "Search again", self._start_scan, (120, 70, 0))
        self._button(img, 24 + bw + 12, h - 70, bw, 56, "Back", self.open)

    def _draw_pin(self, img, w, h):
        _text(img, "PIN for the speaker", 24, 40, 0.9, ORANGE)
        _text(img, "Usually 0000 or 1234 (see the speaker's manual)", 24, 70, 0.55, MUTED, max_w=w // 2 - 44)
        cv2.rectangle(img, (24, 88), (w // 2 - 20, 140), PANEL, -1)
        _text(img, self.pin or "-", 40, 128, 1.1)
        self._button(img, 24, 160, w // 2 - 44, 56, "Try 0000", lambda: self._send_pin("0000"))
        self._button(img, 24, 230, w // 2 - 44, 56, "Cancel", lambda: self._send_pin(None), RED)
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "<", "0", "OK"]
        kx0, kw, kh = w // 2, (w // 2 - 24 - 2 * 8) // 3, 64
        for i, k in enumerate(keys):
            x, y = kx0 + (i % 3) * (kw + 8), 24 + (i // 3) * (kh + 8)
            act = (lambda: self._send_pin(self.pin)) if k == "OK" else (
                (lambda: setattr(self, "pin", self.pin[:-1])) if k == "<" else
                (lambda d=k: setattr(self, "pin", (self.pin + d)[:16])))
            self._button(img, x, y, kw, kh, k, act, BTN_ON if k == "OK" else BTN, 0.9)

    def _draw_result(self, img, w, h):
        ok = self.message.startswith(("Connected", "Sound now", "No speaker", "Playing"))
        _text(img, "Speaker", 24, 44, 1.0, ORANGE)
        _text(img, self.message, 24, 130, 0.75, GREEN if ok else (80, 80, 255), max_w=w - 48)
        self._button(img, 24, h - 70, w - 48, 56, "OK", self.open)

    # ---------- actions ----------
    def _run(self, job, busy_text, *args):
        """Runs `job` in the background; with busy_text the 'please wait' screen is shown meanwhile."""
        if busy_text:
            self.state, self.busy_text = "busy", busy_text
        self._job = threading.Thread(target=job, args=args, daemon=True, name="speaker-ui")
        self._job.start()

    def _load_home(self):
        options = []
        try:
            paired = self.sp.paired_speakers()
            outs = self.sp.outputs()
            muted = self.sp.muted()
            for mac, name, connected in paired:
                on = connected and not muted and any(d and n == name for _, n, d in outs)
                options.append((f"{name}" + ("  (in use)" if on else ""),
                                lambda m=mac, n=name: self._run(self._connect, f"Connecting to {n}...", m, n), on))
            names = {n for _, n, _ in paired}
            for _, name, default in outs:
                if name not in names:
                    options.append((name + ("  (in use)" if default and not muted else ""),
                                    lambda n=name: self._run(self._choose, f"Switching to {n}...", n),
                                    default and not muted))
            options.append(("No speaker (text only)" + ("  (in use)" if muted else ""), self._choose_none, muted))
            current = self.sp.current()
        except Exception as e:                      # Bluetooth / PipeWire not answering: still usable
            options, current = [("No speaker (text only)", self._choose_none, False)], f"unknown ({e})"
        self.home = (current, options)

    def _start_scan(self):
        self._run(self._scan, "Turn your speaker on and put it in pairing mode\n"
                              "(usually: hold its Bluetooth button until the light flashes).\n"
                              "Searching for 10 seconds...")

    def _scan(self):
        try:
            self.found = self.sp.scan(10)
        except Exception:
            self.found = []
        self.state = "found"

    def _start_pair(self, mac, name):
        self._run(self._pair, f"Connecting to {name}...", mac, name)

    def _pair(self, mac, name):
        ok, msg = self.sp.pair(mac, name, self._ask_pin)
        self._done(ok, msg)

    def _ask_pin(self):
        """Called from the pairing thread when the speaker wants a PIN: shows the keypad and waits."""
        self.pin, self._pin_value = "", None
        self._pin_done.clear()
        self.state = "pin"
        self._pin_done.wait(120)
        self.state, self.busy_text = "busy", "Checking the PIN..."
        return self._pin_value

    def _send_pin(self, value):
        self._pin_value = value if value else None
        self._pin_done.set()

    def _connect(self, mac, name):
        self._done(*self.sp.connect(mac, name))

    def _choose(self, name):
        self._done(*self.sp.choose_output(name))

    def _choose_none(self):
        self.sp.use_none()
        if self.voice is not None:
            self.voice.muted = True
        self.message, self.state = "No speaker - FitForm shows everything as text only.", "result"

    def _done(self, ok, msg):
        if ok and self.voice is not None:
            self.voice.muted = False
        self.message, self.state = msg, "result"

    def _test_sound(self):
        if self.voice is None or not self.voice.ready:
            self.message = "The voice is off on this device (no voice model / Piper)."
        elif self.voice.muted:
            self.message = "Choose a speaker first - 'No speaker' is selected."
        else:
            from .voice import SESSION
            self.voice.say("Hello, this is FitForm. Your speaker works.", SESSION, ttl=10)
            self.message = "Playing a test sentence - can you hear it?"
        self.state = "result"
