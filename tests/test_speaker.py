"""Tests for the speaker settings (no Bluetooth or speaker needed: the tools' output is given as text and a fake
backend stands in for bluetoothctl / wpctl). Run from the project folder:  python tests/test_speaker.py"""

import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fitform.speaker import Speakers, parse_devices, parse_info, parse_sinks  # noqa: E402
from fitform.speaker_ui import SpeakerMenu  # noqa: E402

WPCTL = """PipeWire 'pipewire-0' [1.4.2, steve@fitform, cookie:1]
 └─ Clients:
        33. pipewire

Audio
 ├─ Devices:
 │      48. Built-in Audio                      [alsa]
 │      70. JBL Flip 5                          [bluez5]
 │
 ├─ Sinks:
 │      35. Dummy Output                        [vol: 1.00]
 │  *   71. JBL Flip 5                          [vol: 0.40]
 │      52. Built-in Audio Digital Stereo (HDMI) [vol: 0.80]
 │
 ├─ Sources:
 │
 └─ Streams:

Video
 ├─ Devices:
"""


def test_audio_outputs_from_wpctl():
    assert parse_sinks(WPCTL) == [(71, "JBL Flip 5", True), (52, "Built-in Audio Digital Stereo (HDMI)", False)]
    assert parse_sinks("Audio\n ├─ Sinks:\n │  *   35. Dummy Output   [vol: 1.00]\n ├─ Sources:\n") == []


def test_bluetooth_devices_and_info():
    devs = "Device AA:BB:CC:DD:EE:01 JBL Flip 5\nDevice AA:BB:CC:DD:EE:02 AA-BB-CC-DD-EE-02\n" \
           "\x1b[0;94m[bluetooth]\x1b[0m# Device aa:bb:cc:dd:ee:03 Galaxy Watch\n"
    assert parse_devices(devs) == [("AA:BB:CC:DD:EE:01", "JBL Flip 5"), ("AA:BB:CC:DD:EE:03", "Galaxy Watch")]
    speaker = parse_info("Device AA:BB:CC:DD:EE:01 (public)\n\tName: JBL Flip 5\n\tIcon: audio-card\n"
                         "\tPaired: yes\n\tConnected: no\n\tUUID: Audio Sink  (0000110b-0000-1000-8000-00805f9b34fb)\n")
    assert speaker == {"name": "JBL Flip 5", "icon": "audio-card", "paired": True, "connected": False, "audio": True}
    watch = parse_info("Device AA:BB:CC:DD:EE:03\n\tName: Galaxy Watch\n\tIcon: watch\n\tPaired: no\n")
    assert watch["audio"] is False                    # only speakers / headphones are offered


def test_no_speaker_is_remembered():
    with tempfile.TemporaryDirectory() as tmp:
        sp = Speakers(tmp, run=lambda cmd, timeout: WPCTL if cmd[:2] == ["wpctl", "status"] else "")
        assert not sp.muted() and sp.current() == "JBL Flip 5"
        sp.use_none()
        assert sp.muted() and sp.current() == "No speaker (text only)"
        assert Speakers(tmp, run=sp._run).muted()      # still muted after FitForm restarts
        assert sp.restore() is None                   # nothing to reconnect


def test_choosing_an_output_sets_it_as_default():
    calls = []

    def run(cmd, timeout):
        calls.append(cmd)
        return WPCTL if cmd[:2] == ["wpctl", "status"] else ""
    with tempfile.TemporaryDirectory() as tmp:
        sp = Speakers(tmp, run=run)
        ok, msg = sp.choose_output("Built-in Audio Digital Stereo (HDMI)")
        assert ok and ["wpctl", "set-default", "52"] in calls
        assert sp.settings() == {"use": "output", "name": "Built-in Audio Digital Stereo (HDMI)"}
        assert sp.choose_output("Not there")[0] is False


# ---------- the touch screens, with a fake backend ----------
class FakeVoice:
    ready, muted = True, False

    def __init__(self):
        self.said = []

    def say(self, text, prio, **kw):
        self.said.append(text)


class FakeSpeakers:
    def __init__(self, pin_needed=None):
        self.pin_needed = pin_needed                  # e.g. '0000': the speaker asks for this PIN
        self.none = False
        self.paired = [("AA:BB:CC:DD:EE:01", "JBL Flip 5", True)]
        self.got_pin = None

    def muted(self):
        return self.none

    def current(self):
        return "No speaker (text only)" if self.none else "JBL Flip 5"

    def paired_speakers(self):
        return list(self.paired)

    def outputs(self):
        return [(71, "JBL Flip 5", True)]

    def use_none(self):
        self.none = True

    def scan(self, seconds):
        return [("AA:BB:CC:DD:EE:09", "Anker SoundCore")]

    def pair(self, mac, name, ask_pin):
        if self.pin_needed:
            self.got_pin = ask_pin()
            if self.got_pin != self.pin_needed:
                return False, f"Could not pair with {name} (wrong PIN?)"
        self.none = False
        return True, f"Connected to {name}"

    def connect(self, mac, name):
        self.none = False
        return True, f"Connected to {name}"

    def choose_output(self, name):
        return True, f"Sound now plays on {name}"


SCREEN = (480, 800, 3)


def show(menu):
    menu.draw(np.zeros(SCREEN, np.uint8))


def press(menu, label):
    """Taps the button whose label starts with `label` on the screen shown last."""
    show(menu)
    for x0, y0, x1, y1, _, text in menu.buttons:
        if text.startswith(label):
            assert menu.tap((x0 + x1) // 2, (y0 + y1) // 2)
            return
    raise AssertionError(f"no button {label!r} on the {menu.state} screen: {[b[5] for b in menu.buttons]}")


def wait(menu, state, secs=3.0):
    end = time.time() + secs
    while menu.state != state and time.time() < end:
        time.sleep(0.01)
    assert menu.state == state, f"{menu.state} instead of {state}"


def wait_home(menu):
    end = time.time() + 3
    while menu.home is None and time.time() < end:
        time.sleep(0.01)
    assert menu.home is not None


def test_speaker_button_only_between_sessions():
    menu = SpeakerMenu(FakeSpeakers(), FakeVoice())
    img = np.zeros(SCREEN, np.uint8)
    menu.draw(img, allowed=False)
    assert menu.open_rect is None and not menu.tap(700, 30)
    menu.draw(img, allowed=True)
    x0, y0, x1, y1 = menu.open_rect
    assert (x1, y0) == (792, 72) and x0 >= 720        # under the X, inside the right black bar (not over the picture)
    assert menu.tap((x0 + x1) // 2, (y0 + y1) // 2) and menu.is_open


def test_choose_no_speaker_mutes_the_voice():
    sp, voice = FakeSpeakers(), FakeVoice()
    menu = SpeakerMenu(sp, voice)
    menu.open()
    wait_home(menu)
    labels = [o[0] for o in menu.home[1]]
    assert labels == ["JBL Flip 5  (in use)", "No speaker (text only)"]
    press(menu, "No speaker")
    assert sp.none and voice.muted and menu.state == "result"
    press(menu, "OK")
    wait_home(menu)
    press(menu, "Test sound")
    assert "Choose a speaker first" in menu.message and not voice.said
    press(menu, "OK")
    wait_home(menu)
    press(menu, "Close")
    assert not menu.is_open


def test_pair_a_new_speaker_with_a_pin():
    sp, voice = FakeSpeakers(pin_needed="1234"), FakeVoice()
    voice.muted = True
    menu = SpeakerMenu(sp, voice)
    menu.open()
    wait_home(menu)
    press(menu, "Find new speaker")
    wait(menu, "found")
    press(menu, "Anker SoundCore")
    wait(menu, "pin")                                 # the speaker asked for a PIN: keypad shown
    for d in "1235":
        press(menu, d)
    press(menu, "<")                                  # a mistake, corrected
    press(menu, "4")
    assert menu.pin == "1234"
    press(menu, "OK")
    wait(menu, "result")
    assert sp.got_pin == "1234" and menu.message == "Connected to Anker SoundCore" and not voice.muted


def test_speaker_without_pin_and_cancelled_pin():
    menu = SpeakerMenu(FakeSpeakers(), FakeVoice())
    menu.open()
    wait_home(menu)
    press(menu, "Find new speaker")
    wait(menu, "found")
    press(menu, "Anker")
    wait(menu, "result")                              # no PIN asked: straight to the result
    assert menu.message == "Connected to Anker SoundCore"
    sp2 = FakeSpeakers(pin_needed="0000")
    menu2 = SpeakerMenu(sp2, FakeVoice())
    menu2.open()
    wait_home(menu2)
    press(menu2, "Find new speaker")
    wait(menu2, "found")
    press(menu2, "Anker")
    wait(menu2, "pin")
    press(menu2, "Cancel")
    wait(menu2, "result")
    assert sp2.got_pin is None and "Could not pair" in menu2.message


def test_menu_closes_when_training_starts_but_not_while_pairing():
    """22 Nov test: logged in on the phone while the speaker menu was still open on the Pi - training waited
    until the user walked back to tap OK and Close."""
    menu = SpeakerMenu(FakeSpeakers(), FakeVoice())
    assert not menu.close_for_training()                       # already closed: nothing to do
    for state in ("home", "result", "found"):
        menu.open()
        wait_home(menu)
        menu.state = state
        assert menu.close_for_training() and not menu.is_open
    sp = FakeSpeakers(pin_needed="0000")
    menu = SpeakerMenu(sp, FakeVoice())
    menu.open()
    wait_home(menu)
    press(menu, "Find new speaker")
    wait(menu, "found")
    press(menu, "Anker")
    wait(menu, "pin")                                           # waiting for a PIN: must stay open
    assert not menu.close_for_training() and menu.state == "pin"
    press(menu, "Cancel")
    wait(menu, "result")


def test_arm_boards_match_the_mirrored_picture():
    """The picture is mirrored, so the RIGHT arm's board is on the right of the screen and LEFT on the left."""
    from fitform.display_ui import draw_hud
    from fitform.feedback_engine import FeedbackEngine
    img = np.zeros((600, 800, 3), np.uint8)
    draw_hud(img, FeedbackEngine(), 0.0, 0.0, 15.0)
    yellow = (img[:, :, 0] < 50) & (img[:, :, 1] > 200) & (img[:, :, 2] > 200)       # the 'RIGHT' label
    magenta = (img[:, :, 0] > 200) & (img[:, :, 1] < 150) & (img[:, :, 2] > 200)     # the 'LEFT' label
    assert np.nonzero(yellow[:40])[1].min() > 600 and np.nonzero(magenta[:40])[1].max() < 200


def test_test_sound_plays_on_the_chosen_speaker():
    voice = FakeVoice()
    menu = SpeakerMenu(FakeSpeakers(), voice)
    menu.open()
    wait_home(menu)
    press(menu, "Test sound")
    assert voice.said == ["Hello, this is FitForm. Your speaker works."]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("passed", name)
