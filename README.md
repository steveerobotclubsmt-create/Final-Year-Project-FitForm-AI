# FitForm AI - Pose-Based Personal Trainer

**Project videos:** see [VIDEOS.md](VIDEOS.md)

Project documents (Gantt chart, figures): [docs/](docs/README.md)

Individual Major Project (6FTC2062), BEng Robotics and Artificial Intelligence, University of Hertfordshire.

FitForm AI uses a camera, MediaPipe Pose and OpenCV on a Raspberry Pi 5 to count bicep curl repetitions and check exercise form in real time. It gives feedback through an on-screen overlay, green/red LEDs and a buzzer, and logs each session to a CSV file that can be downloaded over Wi-Fi.

## Features
- Real-time pose detection (MediaPipe Pose + OpenCV), 2D joint angles
- Rep counting per arm. A rep only counts if it starts from a straight arm, the upper arm points down and stays by the side, the hand grips the weight (fist, or fingers round a bottle / dumbbell), the wrist stays straight, the lift is neither too fast nor too slow and the arm is not dropped back down too fast. The lift and the lowering are timed from the wrist's height, and a rep counts once the arm is back down
- Weight-in-hand check (CNN): a small neural network (MobileNetV3-Small, fine-tuned on hand pictures from labelled clips) looks at each hand on the front camera and decides "holding a weight" or "empty hand", once per rep. It is advice only: when it happened in 2 or more reps, the phone page shows a "No weight in your hand?" card with pictures. See "Weight-in-hand CNN" below
- Two cameras: Raspberry Pi AI Camera in front (counting) + USB webcam at the side (`--side-camera 0`); either camera can confirm the grip
- When a curl is not counted, the screen shows why and what to do (e.g. "Keep your upper arm pointing down"), with a short pause before the next rep
- Start-up demo: an animated stick figure showing a correct curl and the key rules (fist facing the body)
- No keyboard needed: the window opens full screen, and a session ends when you walk away (5 s) or stop curling (30 s)
- Camera watchdog: if the Pi camera sends no picture for 3 s (seen when the Pi was hot and throttled), it is restarted by itself
- Accounts on the phone app (username + password, body weight). The device screen shows a QR code: scan it, log in, tap **Train on this device**; the session is saved to your account and the device logs out afterwards. Curls only count after logging in (`REQUIRE_LOGIN` in `fitform/config.py`; not needed with `--no-server` or `--video`). A forgotten password can be reset on the device with `tools/reset_password.py`
- Phone app dashboard: next session goal (sets x reps per arm, kcal, minutes), sessions this week, calories per session against each session's goal, last session, why curls were not counted, history, CSV download
- Goals from published guidelines (see "Where the goals come from")
- Fist direction and grip (hand not clenched) are advisory (see Known limitations): the rep still counts, and the app shows a warning with pictures from the cameras when it happened in 2 or more reps
- Green/red LED form indicator and buzzer (Raspberry Pi GPIO)
- Calorie estimate: MET x body weight x active time (from the first to the last curl)
- Session log: CSV (`logs/sessions.csv`) plus a detailed history (`logs/sessions.jsonl`)

## Project structure
```
fitform-ai/
├── main.py                  # entry point - runs the whole system
├── VIDEOS.md                # links to the demo videos
├── fitform/
│   ├── config.py            # all settings (cameras, thresholds, GPIO pins, sessions...)
│   ├── camera_detect.py     # finds the cameras: AI Camera front, USB webcam side or front
│   ├── camera_thread.py     # background camera capture (no lag / buffering)
│   ├── pose_engine.py       # MediaPipe Pose wrapper
│   ├── bicep_curl.py        # joint angles + rep-counting state machine
│   ├── hand_check.py        # MediaPipe Hands: fist / grip and fist direction per arm
│   ├── hand_state.py        # fist / grip and direction classification (no camera needed)
│   ├── fist_calib.py        # optional per-arm fist-direction calibration
│   ├── side_palm.py         # side camera: palm direction and grip
│   ├── hold_check.py        # weight-in-hand CNN: cuts the hand picture and runs the model (OpenCV DNN)
│   ├── feedback_engine.py   # runs the rep counters and chooses the feedback text
│   ├── display_ui.py        # on-screen overlay, demo, QR code and 'session saved' screens
│   ├── gpio_feedback.py     # LEDs + buzzer (auto-disabled on a laptop)
│   ├── calorie_tracker.py   # MET-based calorie estimate
│   ├── session.py           # ends a session when the user walks away or stops
│   ├── session_summary.py   # end-of-session totals
│   ├── plan.py              # goal for the next session (ACSM / WHO / Compendium)
│   └── session_logger.py    # accounts, session storage and the phone app (Flask)
├── models/
│   ├── hand_holding.onnx    # trained weight-in-hand CNN (MobileNetV3-Small, ONNX)
│   └── hand_holding_report.txt   # training data and test results of the CNN
├── tools/
│   ├── fist_calibrate.py    # builds the fist-direction calibration from labelled runs
│   ├── record_clips.py      # records labelled two-camera test clips (rep checks and CNN training data)
│   ├── hand_crops.py        # cuts labelled hand pictures out of the clips for training
│   ├── train_hand_classifier.py  # trains the CNN and writes models/ (PyTorch, runs in ~/cnn_env)
│   ├── imx500_bottle_test.py     # test: can the AI Camera's on-chip object detector see a bottle?
│   └── reset_password.py    # sets a new password for an account
├── prototypes/
│   └── bicep_curl_single_camera.py   # original single-file laptop prototype
├── docs/
│   ├── README.md            # list of the project documents
│   ├── gantt/               # Gantt chart (Excel, PDF, picture)
│   └── figures/             # block diagrams and figures for the logbooks/report
├── tests/
│   └── test_logic.py        # tests for counting, goals, accounts and the app (no camera needed)
├── logs/                    # sessions, accounts, hand pictures, clips and training crops (not uploaded to GitHub)
└── requirements.txt
```

## Setup

### Windows laptop (development)
```powershell
python -m venv C:\Users\<you>\fitform_env
C:\Users\<you>\fitform_env\Scripts\activate
pip install -r requirements.txt
```
Keep the virtual environment outside OneDrive. Syncing thousands of package files slows everything down.

### Raspberry Pi 5 (Raspberry Pi OS Trixie, 64-bit)
Trixie ships Python 3.13, but the MediaPipe Pose API used here (`mediapipe==0.10.18`) only has Pi (aarch64) builds for Python 3.11/3.12. So FitForm gets its own Python 3.12 environment, installed with `uv`, next to the system Python.
```bash
sudo apt update && sudo apt install -y libportaudio2 rpicam-apps git
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv venv --python 3.12 ~/fitform_env
source ~/fitform_env/bin/activate
cd ~/Final-Year-Project-FitForm-AI
uv pip install -r requirements.txt
```
The Pi Camera Module is read through the `rpicam-vid` command (`--camera picam`), so Picamera2 is not needed inside the environment. A USB webcam uses `--camera 0`.

Check the install:
```bash
python -c "import mediapipe as mp, cv2; mp.solutions.pose.Pose(); print('MediaPipe', mp.__version__, 'OpenCV', cv2.__version__)"
rpicam-hello --list-cameras     # Pi Camera Module detected?
```

## Usage
Run from the project folder (on the Pi, first `source ~/fitform_env/bin/activate`):
```bash
python main.py                    # finds the cameras by itself (see below)
python main.py --no-side          # use one camera even if two are connected
python main.py --camera picam --rotate 180 --side-camera 0   # choose the cameras yourself
python main.py --weight 65        # your body weight in kg for calories
python main.py --video clip.mp4   # test on a recorded video
python main.py --no-demo --no-gpio --no-server --debug
python main.py --windowed         # normal window instead of full screen
python main.py --no-hold          # turn off the weight-in-hand CNN
```
Cameras are found automatically: the Raspberry Pi AI Camera is the front camera when it is connected and a
USB webcam becomes the side camera; without the AI Camera, the USB webcam is the front camera. At least one
camera is needed. The AI Camera picture is turned 180 degrees (it is mounted upside down) - change
`PICAM_ROTATE` / `WEBCAM_ROTATE` in `fitform/config.py` if your mounting differs.

With nobody in front of it, the device shows a QR code with its address (e.g. `http://192.168.1.23:5000`).
Scan it with a phone on the same Wi-Fi, log in or create an account, and tap **Train on this device**.
A session ends by itself when you walk out of view for 5 s or stop curling for 30 s; the screen then shows
the totals and your next goal, and everything is on the phone app.
(With a keyboard: **Q** quits and saves, **R** resets.)

Optional: `tools/fist_calibrate.py` builds a per-arm calibration of the fist-direction reading from labelled
`--debug` runs (instructions at the top of the file). Thresholds are in `fitform/config.py`.

### Camera set-up
- Stand about **2-3 m** from the front camera so your whole upper body, elbows and both hands stay in view.
- Side webcam: level with your hip, as close to 90 degrees from the front as the cable allows.
- Good, even lighting; avoid a bright window behind you.

Other addresses: `http://<pi-ip>:5000/sessions` (JSON), `http://<pi-ip>:5000/sessions.csv` (download).

## Weight-in-hand CNN
FitForm checks whether there is actually a weight in the hand with a small image classifier: MobileNetV3-Small
(pretrained on ImageNet, last layer replaced by 2 outputs "empty" / "holding", all layers fine-tuned) on a
128x128 picture cut around each hand, just past the wrist along the forearm.

How it was made (27 Oct 2026, data in `models/hand_holding_report.txt`):
1. `tools/record_clips.py hands <round>` records labelled clips from both cameras: bottle in the right hand,
   bottle in the left hand, empty fist, open hand.
2. `tools/hand_crops.py` uses MediaPipe Pose to find each wrist and saves the hand picture, labelled from the
   clip name (round 1: 4902 pictures, round 2: 4654 pictures).
3. `tools/train_hand_classifier.py` trains the model with PyTorch and exports `models/hand_holding.onnx`.

Results: trained on round 1 and tested on round 2 (a new session, other position and light), the front camera
was right on **98.5 %** of 4654 pictures (bottle 95.5 %, empty fist 99.5 %, open hand 97.3 %). The final model
is trained on both rounds.

In FitForm the model runs through OpenCV's DNN module (about 5 ms per hand), so `fitform_env` does not need
PyTorch. The hands are classified every 3rd frame and each rep gets one vote: with at least 3 readings and
60 % or more of them "empty", the rep is marked "no weight". This is advice only (`HOLD_REJECTS = False` in
`fitform/config.py`): the rep still counts. `--no-hold` turns the check off.

Training needs PyTorch, which is kept in its own environment so the app's environment stays small:
```bash
python3 -m venv ~/cnn_env
~/cnn_env/bin/pip install torch torchvision pillow numpy onnx
~/cnn_env/bin/python tools/train_hand_classifier.py --train 1 --test 2
```

## Where the goals come from
- Sets and reps: novices 1-3 sets of 8-12 reps; add 2-10 % load once 1-2 extra reps are possible on two
  consecutive sessions; 1-2 min rest for assistance exercises - Ratamess et al., ACSM position stand,
  *Med Sci Sports Exerc* 2009;41(3):687-708. The app uses a ladder 3x8 -> 3x10 -> 3x12 reps per arm (a step up
  when the goal is reached with at least 85 % of curls counted), then a weight increase and back to 3x8.
- At least 2 sessions a week: WHO Guidelines on Physical Activity and Sedentary Behaviour (2020).
- Calories: MET 3.5, "resistance training, multiple exercises, 8-15 reps" (2024 Adult Compendium of Physical
  Activities, code 02054); kcal = MET x body weight x hours. The kcal goal is the estimate for doing the
  session's goal at about 3 s per rep with 60 s rests.

## Known limitations
- **Fist direction (turned outward vs. facing the body)** cannot be detected reliably. Tested with one camera,
  two cameras and a per-arm calibration from labelled runs (21 Oct 2026): the reading separates the two cases
  within one session, but the same correct curl can read anywhere from "correct" to "turned out" between reps
  and sessions (it depends on small wrist rotations and on camera placement). It is therefore advisory only.
- **Clenched fist vs. open hand** is judged from the hand landmarks, which flicker frame to frame, and a hand
  round a bottle or dumbbell can look open. It is therefore advisory as well.
- **Weight in the hand (CNN)** is trained on one person, one plastic bottle and one room, with no dumbbell yet.
  Mistakes seen: motion-blurred open hands, and a yellow pole in the background read as the (yellow) bottle.
  It is therefore advisory only. Next step: a new test set with a 3D-printed dumbbell, a different-coloured
  object and ideally other people.
- Accounts are stored on each device; several devices sharing one account list would need a central server.
- **Correct curls are counted reliably; wrong ones less so** - the arm checks (upper arm, elbow, tempo,
  extension) catch bad reps well, the hand checks less consistently.
- Calories are an estimate (MET formula), not a measurement. The plan is general guidance, not coaching.
- Frame rate on the Pi 5 is about 13-16 FPS with two cameras, so very fast reps can be timed less accurately.

## Wiring (default BCM pins, change in `fitform/config.py`)
| Component | GPIO pin | Notes |
|---|---|---|
| Green LED | GPIO 17 | via 220-330 Ω resistor to GND |
| Red LED | GPIO 27 | via 220-330 Ω resistor to GND |
| Buzzer (active, 5V/3.3V) | GPIO 22 | other leg to GND |

## Tests
```bash
python tests/test_logic.py
```

## Tested versions
mediapipe 0.10.21, opencv-python 4.11.0.86, numpy 1.26, Python 3.10-3.12.
MediaPipe 1.0+ removed the `mp.solutions.pose` API this project uses, so keep the version pinned.

## Privacy
Video is processed in memory and not recorded. Exercise numbers are logged on the Pi; passwords are stored
hashed (PBKDF2) in `logs/users.json`. When a rep looked like it was
done with the fist turned out, the hand not gripping or no weight in the hand, a small picture of the hand is saved
in `logs/snaps/` (at most 6 per session) so you can check it on the phone page; it is only reachable on the local Wi-Fi. Set `MAX_SNAPSHOTS = 0` in
`fitform/config.py` to turn this off, and delete `logs/` to remove all data.
