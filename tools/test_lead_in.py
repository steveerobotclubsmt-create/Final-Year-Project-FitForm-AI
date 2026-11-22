"""Finds how much silence a speaker needs before each sentence so the first word is not cut off.
Plays 'Right, 1' ... 'Right, 4' with 0, 0.2, 0.4 and 0.6 s of silence before them, with a quiet gap between, while
recording exactly what the Pi sends to the speaker (the default audio output) into a WAV file. Run from the
project folder (fitform_env active), with FitForm closed:
  python tools/test_lead_in.py                     # into logs/test_runs/<date_time>/
  python tools/test_lead_in.py --gap 10            # a longer quiet gap (more time for the speaker to fall asleep)
Listen: the first number whose 'Right' you hear completely shows the silence the speaker needs - set it as
VOICE_LEAD_IN_SECONDS in fitform/config.py. (The recording shows what was sent; if a speaker swallows the start
of a word, that happens inside the speaker, so it is not in the recording.)"""

import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fitform import config  # noqa: E402
from fitform.voice import Voice  # noqa: E402

LEADS = (0.0, 0.2, 0.4, 0.6)


def default_sink():
    out = subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True).stdout
    name = desc = None
    for line in out.splitlines():
        line = line.strip().lstrip("* ")
        if line.startswith("node.name"):
            name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("node.description"):
            desc = line.split("=", 1)[1].strip().strip('"')
    return name, desc


def add_opener(src, dst, kind, level, seconds=0.3, gap=0.12):
    """Copies WAV `src` to `dst` with a short sound before it: 'quiet hiss' / 'louder hiss' (noise of `level`)
    or 'soft chime' (an 880 Hz tone fading out), then `gap` s of silence."""
    import wave
    import numpy as np
    with wave.open(src) as r:
        params, frames = r.getparams(), r.readframes(r.getnframes())
    sr, ch = params.framerate, params.nchannels
    t = np.arange(int(sr * seconds)) / sr
    if kind == "soft chime":
        sound = np.sin(2 * np.pi * 880 * t) * np.exp(-t / 0.08) * level
    else:
        sound = np.random.default_rng(1).standard_normal(len(t)) * level * np.minimum(1, t / 0.05)
    pre = np.concatenate([sound, np.zeros(int(sr * gap))])
    pre = (np.repeat(pre[:, None], ch, axis=1).ravel() * 32767).astype(np.int16).tobytes()
    with wave.open(dst, "wb") as w:
        w.setparams(params)
        w.writeframes(pre + frames)


def main():
    ap = argparse.ArgumentParser(description="Silence-before-sentence test with a recording")
    ap.add_argument("--gap", type=float, default=6.0, help="quiet seconds before each test sentence")
    ap.add_argument("--out", help="folder for the recording (default logs/test_runs/<date_time>)")
    ap.add_argument("--opener", action="store_true",
                    help="after a warm-up sentence: 3 ways to wake the speaker before 'Right, N' - a quiet hiss, "
                         "a louder hiss and a short soft chime (0.3 s each, then the sentence)")
    ap.add_argument("--chime-all", action="store_true", help="after a warm-up sentence: all four with the chime")
    ap.add_argument("--keepalive", type=float, default=0.0, metavar="LEVEL",
                    help="play an inaudible hiss of this level (e.g. 0.001) all the time, so the speaker never "
                         "mutes itself; all sentences then without silence before them")
    args = ap.parse_args()
    out = args.out or os.path.join(ROOT, config.LOG_DIR, "test_runs", time.strftime("%Y%m%d_%H%M%S") + "_audio")
    os.makedirs(out, exist_ok=True)

    sink, desc = default_sink()
    print(f"Sound output: {desc or sink or 'unknown'}")
    voice = Voice(start=False)
    if not voice.ready:
        sys.exit("The voice could not be started.")
    leads = (0.0,) * 4 if args.keepalive else LEADS
    clips = [(lead, f"Right, {i}. Left, {i}.", voice._piper_synth(f"Right, {i}. Left, {i}.", lead_in=lead))
             for i, lead in enumerate(leads, 1)]                      # made before playing, so no delay
    if args.opener or args.chime_all:
        clips = [(0.0, "Ready.", voice._piper_synth("Ready.", lead_in=0.0))]
        kinds = [("soft chime", 0.15)] * 4 if args.chime_all else \
            [("quiet hiss", 0.01), ("louder hiss", 0.05), ("soft chime", 0.15)]
        for i, (kind, level) in enumerate(kinds, 1):
            text = f"Right, {i}. Left, {i}."
            dst = os.path.join(out, f"opener_{i}.wav")
            add_opener(voice._piper_synth(text, lead_in=0.0), dst, kind, level)
            clips.append((kind, text, dst))
    hiss = None
    if args.keepalive:
        import numpy as np
        import wave
        hp = os.path.join(out, "keepalive_hiss.wav")
        with wave.open(clips[0][2]) as r:
            sr, ch = r.getframerate(), r.getnchannels()
        n = int(sr * 120)
        data = (np.random.default_rng(0).standard_normal(n * ch) * 32767 * args.keepalive).astype(np.int16)
        with wave.open(hp, "wb") as w:
            w.setnchannels(ch), w.setsampwidth(2), w.setframerate(sr)
            w.writeframes(data.tobytes())
        hiss = subprocess.Popen(["pw-play", hp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Inaudible hiss (level {args.keepalive}) playing all the time")

    wav = os.path.join(out, "audio_test.wav")
    rec = None
    if shutil.which("pw-record") and sink:
        rec = subprocess.Popen(["pw-record", "--target", sink, "-P", "{ stream.capture.sink=true }", wav],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    with open(os.path.join(out, "audio_test_log.txt"), "w") as log:
        log.write(f"output: {desc or sink}\ngap before each sentence: {args.gap} s\n"
                  f"keep-alive hiss: {args.keepalive or 'none'}\n")
        for i, (lead, text, path) in enumerate(clips, 1):
            time.sleep(args.gap)
            what = lead if isinstance(lead, str) else f"{lead:.1f} s silence"
            line = f"{time.time() - t0:6.2f} s  test {i}: {what}, then '{text}'"
            print(line, flush=True)
            log.write(line + "\n")
            subprocess.run(["pw-play", path] if shutil.which("pw-play") else ["aplay", "-q", path])
        time.sleep(1.0)
    if hiss:
        hiss.terminate()
    if rec:
        rec.terminate()
        rec.wait(timeout=5)
        print(f"Recorded what was sent to the speaker: {wav}")
    print("Which was the first test where you heard 'Right' completely? (1 = no silence ... 4 = 0.6 s)")


if __name__ == "__main__":
    main()
