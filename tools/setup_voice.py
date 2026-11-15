"""One-time set-up of the spoken feedback, run on the device from the project folder (fitform_env active):
  python tools/setup_voice.py             # download the voice (63 MB, once), make all fixed phrases, test speaker
  python tools/setup_voice.py --no-test   # the same without the test sentence
The phrases are kept in ~/.cache/fitform/voice, so the app never has to make them while someone trains
(it would otherwise make them in the background on its first run). Change the voice with VOICE_MODEL in
fitform/config.py - any Piper voice name works, e.g. en_US-lessac-medium."""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fitform import config  # noqa: E402
from fitform.coach import Coach  # noqa: E402
from fitform.voice import SESSION, Voice  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Download the voice and prepare the spoken phrases")
    p.add_argument("--no-test", action="store_true", help="do not play the test sentence")
    args = p.parse_args()

    model = Voice._model_path(config.VOICE_MODEL)
    if not os.path.exists(model):
        name = os.path.basename(model).rsplit(".onnx", 1)[0]
        print(f"Downloading the voice {name} to {os.path.dirname(model)} ...")
        from pathlib import Path
        from piper.download_voices import download_voice
        os.makedirs(os.path.dirname(model), exist_ok=True)
        download_voice(name, Path(os.path.dirname(model)))

    voice = Voice(start=False)
    if not voice.ready:
        sys.exit("The voice could not be started (see the message above).")
    phrases = list(dict.fromkeys(Coach(voice).phrases()))
    t = time.time()
    for i, text in enumerate(phrases, 1):
        voice._piper_synth(text)
        print(f"\rPreparing phrases {i}/{len(phrases)}", end="", flush=True)
    print(f"\nDone in {time.time() - t:.0f} s - kept in {voice._cache}")

    if not args.no_test:
        print("Playing a test sentence - you should hear it from the speaker.")
        voice.say("Hello! The FitForm voice is ready.", SESSION)
        voice.speak_now(voice.next_item())


if __name__ == "__main__":
    main()
