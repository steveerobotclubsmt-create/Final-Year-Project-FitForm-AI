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


def main():
    ap = argparse.ArgumentParser(description="Silence-before-sentence test with a recording")
    ap.add_argument("--gap", type=float, default=6.0, help="quiet seconds before each test sentence")
    ap.add_argument("--out", help="folder for the recording (default logs/test_runs/<date_time>)")
    args = ap.parse_args()
    out = args.out or os.path.join(ROOT, config.LOG_DIR, "test_runs", time.strftime("%Y%m%d_%H%M%S") + "_audio")
    os.makedirs(out, exist_ok=True)

    sink, desc = default_sink()
    print(f"Sound output: {desc or sink or 'unknown'}")
    voice = Voice(start=False)
    if not voice.ready:
        sys.exit("The voice could not be started.")
    clips = [(lead, f"Right, {i}. Left, {i}.", voice._piper_synth(f"Right, {i}. Left, {i}.", lead_in=lead))
             for i, lead in enumerate(LEADS, 1)]                      # made before playing, so no delay

    wav = os.path.join(out, "audio_test.wav")
    rec = None
    if shutil.which("pw-record") and sink:
        rec = subprocess.Popen(["pw-record", "--target", sink, "-P", "{ stream.capture.sink=true }", wav],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    with open(os.path.join(out, "audio_test_log.txt"), "w") as log:
        log.write(f"output: {desc or sink}\ngap before each sentence: {args.gap} s\n")
        for i, (lead, text, path) in enumerate(clips, 1):
            time.sleep(args.gap)
            line = f"{time.time() - t0:6.2f} s  test {i}: {lead:.1f} s silence, then '{text}'"
            print(line, flush=True)
            log.write(line + "\n")
            subprocess.run(["pw-play", path] if shutil.which("pw-play") else ["aplay", "-q", path])
        time.sleep(1.0)
    if rec:
        rec.terminate()
        rec.wait(timeout=5)
        print(f"Recorded what was sent to the speaker: {wav}")
    print("Which was the first test where you heard 'Right' completely? (1 = no silence ... 4 = 0.6 s)")


if __name__ == "__main__":
    main()
