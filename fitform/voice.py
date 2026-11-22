"""Spoken feedback: offline text-to-speech with Piper (a neural voice that runs on the Pi's CPU, no internet).

One voice, one sentence at a time - nothing ever talks over anything else:
  - say() only fills ONE waiting slot. A more important sentence replaces a less important one that is still
    waiting; a less important one is dropped while something more important waits.
  - The sentence being spoken is never cut off; the next one waits for it.
  - Every sentence has a time limit (ttl): a rep number or a tip that could not be said in time is dropped
    instead of being said late, when it would no longer match what the user is doing.
  - A sentence with a `key` is not said again within its cooldown.
Sentences are made once and kept as WAV files (~/.cache/fitform/voice), so a phrase said before plays at once;
the fixed phrases are made in the background at start-up. Synthesis uses one CPU core at low priority, so the
camera loop keeps its speed. Without a voice model, Piper or a speaker it stays silent and the app runs as before."""

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import wave

from . import config

# priorities: a higher one replaces a lower one that is still waiting
COUNT, TIP, REJECT, SESSION = 1, 2, 3, 4


class _Item:
    __slots__ = ("text", "prio", "key", "until", "parts")

    def __init__(self, text, prio, key, until, parts=None):
        self.text, self.prio, self.key, self.until, self.parts = text, prio, key, until, parts


class Voice:
    """synth(text) -> WAV path and play(path) can be replaced (tests); by default Piper and pw-play/aplay."""

    def __init__(self, enabled=True, model=None, synth=None, play=None, clock=time.monotonic, start=True):
        self.clock = clock
        self._cond = threading.Condition()
        self._pending = None
        self._speaking = None             # _Item being spoken now
        self._last_said = {}              # key -> time it was last said (or queued)
        self._running = False
        self._player = None               # current player process (stopped by close())
        self._warned = set()
        self.spoken = []                  # everything said, oldest first (for tests and --debug)
        self._synth, self._play = synth, play
        self._piper = None
        self.muted = False                # 'No speaker (text only)' chosen in the speaker settings
        self.ready = False
        if not enabled:
            return
        if self._synth is None:
            self._synth = self._piper_synth
            self._model = self._model_path(model or config.VOICE_MODEL)
            if not os.path.exists(self._model):
                print(f"[VOICE] off: no voice model at {self._model} (see README: 'Spoken feedback')")
                return
            try:
                import piper  # noqa: F401  (checked here so a missing package is reported at start-up)
            except ImportError:
                print("[VOICE] off: Piper is not installed (pip install piper-tts)")
                return
            name = os.path.basename(self._model).rsplit(".onnx", 1)[0]
            self._cache = os.path.join(os.path.expanduser(config.VOICE_CACHE_DIR), name)
            os.makedirs(self._cache, exist_ok=True)
        if self._play is None:
            self._play = self._system_play
            if not (shutil.which("pw-play") or shutil.which("aplay")):
                print("[VOICE] off: no audio player found (pw-play or aplay)")
                return
        self.ready = True
        self._threads = []
        if start:
            self._running = True
            self._start_thread(self._worker, "voice")

    # ---------- what the app calls ----------
    def say(self, text, prio, key=None, cooldown=0.0, ttl=None, parts=None):
        """Queue `text`. Returns True if it was accepted (it can still be dropped later if it waits too long).
        `parts`: ready-made sentences that together say `text` - joined instead of making a new sentence."""
        if not self.ready or not text or self.muted:
            return False
        now = self.clock()
        with self._cond:
            if key is not None and now - self._last_said.get(key, -1e9) < cooldown:
                return False
            p = self._pending
            if p is not None and p.until >= now and p.prio > prio:
                return False                    # something more important is already waiting
            self._pending = _Item(text, prio, key, now + (ttl if ttl is not None else 1e9), parts)
            if key is not None:
                self._last_said[key] = now
            self._cond.notify()
        return True

    def busy(self):
        """True while something is being said or waiting to be said."""
        with self._cond:
            return self._speaking is not None or self._pending is not None

    def said_recently(self, key, seconds):
        return self.clock() - self._last_said.get(key, -1e9) < seconds

    def prepare(self, texts):
        """Makes the WAV files for `texts` in the background, so they play at once later."""
        if not self.ready or self._synth != self._piper_synth or not self._running:
            return
        self._start_thread(self._prepare, "voice-prepare", list(texts))

    def close(self, timeout=3.0):
        """Stops speaking and waits for the voice threads. A thread killed in the middle of making a sentence
        (Python exiting) aborts the whole program with 'terminate called without an active exception'."""
        self._running = False
        with self._cond:
            self._pending = None
            self._cond.notify_all()
        p = self._player
        if p is not None and p.poll() is None:
            p.terminate()
        end = time.monotonic() + timeout
        for t in getattr(self, "_threads", []):
            t.join(max(0.0, end - time.monotonic()))

    def _start_thread(self, target, name, *args):
        t = threading.Thread(target=target, args=args, daemon=True, name=name)
        self._threads.append(t)
        t.start()

    # ---------- worker ----------
    def next_item(self):
        """Takes the waiting sentence if it is still in time (else drops it). Used by the worker and the tests."""
        with self._cond:
            item, self._pending = self._pending, None
        if item is not None and self.clock() > item.until:
            return None
        return item

    def speak_now(self, item):
        with self._cond:
            self._speaking = item
        try:
            path = self._synth_item(item)
            if path and self.clock() <= item.until + 0.5:     # (making a new sentence takes a moment)
                self.spoken.append(item.text)
                print(f'[VOICE] "{item.text}"')
                self._play(path)
        except Exception as e:                                 # a broken speaker must never stop the workout
            self._warn_once(type(e).__name__, f"[VOICE] could not speak ({e})")
        finally:
            with self._cond:
                self._speaking = None

    def _synth_item(self, item):
        """WAV for the item. Several ready-made parts ('Right, 6' + 'Left, 5') are joined: making the whole sentence
        new took longer than its time limit on a hot Pi, and both numbers were dropped (22 Nov)."""
        if not item.parts or len(item.parts) < 2 or self._synth != self._piper_synth:
            return self._synth(item.text)
        h = hashlib.sha1(("|".join(item.parts) + f"|{config.VOICE_VOLUME}|{config.VOICE_SPEED}|"
                          f"{config.VOICE_LEAD_IN_SECONDS}|joined").encode()).hexdigest()[:16]
        path = os.path.join(self._cache, h + ".wav")
        if not os.path.exists(path):
            tmp = f"{path}.{threading.get_ident()}.tmp"
            join_wavs([self._piper_synth(p, lead_in=0.0) for p in item.parts], tmp,
                      gap=0.25, lead_in=config.VOICE_LEAD_IN_SECONDS)
            os.replace(tmp, path)
        return path

    def _worker(self):
        _low_priority()
        while self._running:
            with self._cond:
                while self._running and self._pending is None:
                    self._cond.wait(0.5)
            if not self._running:
                break
            item = self.next_item()
            if item is not None:
                self.speak_now(item)

    def _prepare(self, texts):
        _low_priority()
        for t in texts:
            while self._running and self.busy():   # something to say now: it goes first
                time.sleep(0.05)
            if not self._running:
                break
            try:
                self._piper_synth(t)
            except Exception as e:
                self._warn_once("prepare", f"[VOICE] could not prepare phrases ({e})")
                break

    # ---------- Piper + audio ----------
    @staticmethod
    def _model_path(path):
        if os.path.isabs(path):
            return path
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)

    def _load_piper(self):
        import onnxruntime as ort
        from piper.config import PiperConfig, SynthesisConfig
        from piper.voice import PiperVoice
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1          # one core: pose and hand detection keep the others
        opts.inter_op_num_threads = 1
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        with open(self._model + ".json", encoding="utf-8") as f:
            cfg = PiperConfig.from_dict(json.load(f))
        voice = PiperVoice(config=cfg, session=ort.InferenceSession(self._model, sess_options=opts,
                                                                     providers=["CPUExecutionProvider"]))
        syn = SynthesisConfig(volume=config.VOICE_VOLUME, length_scale=1.0 / max(0.5, config.VOICE_SPEED))
        return voice, syn

    def _piper_synth(self, text, lead_in=None):
        lead_in = config.VOICE_LEAD_IN_SECONDS if lead_in is None else lead_in
        h = hashlib.sha1(f"{text}|{config.VOICE_VOLUME}|{config.VOICE_SPEED}|{lead_in}".encode()).hexdigest()[:16]
        path = os.path.join(self._cache, h + ".wav")
        if os.path.exists(path):
            return path
        with _synth_lock:                      # the worker and the prepare thread share one Piper voice
            if self._piper is None:
                self._piper = self._load_piper()
            voice, syn = self._piper
            tmp = f"{path}.{threading.get_ident()}.tmp"
            with wave.open(tmp, "wb") as w:
                voice.synthesize_wav(text, w, syn_config=syn)
        if lead_in > 0:
            add_lead_in(tmp, lead_in)
        os.replace(tmp, path)
        return path

    def _system_play(self, path):
        exe = shutil.which("pw-play")
        cmd = [exe, path] if exe else ["aplay", "-q", path]
        self._player = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _, err = self._player.communicate(timeout=30)
        if self._player.returncode not in (0, None) and self._running:
            self._warn_once("play", f"[VOICE] audio player failed - is a speaker connected? "
                                    f"({(err or b'').decode(errors='ignore').strip()[:120]})")

    def _warn_once(self, key, text):
        if key not in self._warned:
            self._warned.add(key)
            print(text)


_synth_lock = threading.Lock()


def add_lead_in(path, seconds):
    """Puts `seconds` of silence before the sound in the WAV file `path`. A Bluetooth speaker that has been quiet
    goes into power-saving and swallows the first fraction of a second of the next sound - on 22 Nov the first
    word, 'Right' or 'Left', was cut off; it now wakes up during the silence instead."""
    with wave.open(path, "rb") as r:
        params, frames = r.getparams(), r.readframes(r.getnframes())
    silence = b"\x00" * (int(params.framerate * seconds) * params.sampwidth * params.nchannels)
    with wave.open(path, "wb") as w:
        w.setparams(params)
        w.writeframes(silence + frames)


def join_wavs(paths, out, gap=0.25, lead_in=0.0):
    """Writes the WAV files `paths` one after another into `out`, with `gap` s of silence between them."""
    params, chunks = None, []
    for p in paths:
        with wave.open(p, "rb") as r:
            params = params or r.getparams()
            chunks.append(r.readframes(r.getnframes()))
    frame = params.sampwidth * params.nchannels
    silence = lambda s: b"\x00" * (int(params.framerate * s) * frame)      # noqa: E731
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(silence(lead_in) + silence(gap).join(chunks))


def _low_priority():
    """Lower this thread's CPU priority (Linux), so speech never slows the camera loop."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except (AttributeError, OSError):
        pass
