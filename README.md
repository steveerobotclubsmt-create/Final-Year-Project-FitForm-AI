# FitForm AI - Pose-Based Personal Trainer

Individual Major Project (6FTC2062), BEng Robotics and Artificial Intelligence, University of Hertfordshire.

FitForm AI uses a camera, MediaPipe Pose and OpenCV on a Raspberry Pi 5 to count bicep curl repetitions and check exercise form in real time. It gives feedback through an on-screen overlay, green/red LEDs and a buzzer, and logs each session to a CSV file that can be downloaded over Wi-Fi.

## Features
- Real-time pose detection (MediaPipe Pose + OpenCV)
- Strict rep counting per arm: a rep only counts if the upper arm stays where it started, the wrist stays straight and the hand is a clenched fist, starting from full extension
- 3D joint angles from MediaPipe world landmarks, so it works from the front or the side
- Fist check with MediaPipe Hands (open palm = rep not counted)
- Live feedback: "Keep elbow still!", "Straighten your wrist!", "Clench your fist!", "Extend arm fully!", "Step back - keep your hands in view"
- Single-camera version (a two-camera front + side version is in development)
- Green/red LED form indicator and buzzer beep on every counted rep (Raspberry Pi GPIO)
- Calorie estimate (MET x weight x active time; timer starts on the first rep)
- Session log (CSV) with reps, form accuracy, duration, calories and average rep speed
- Flask web server to view or download the session log from another device

## Project structure
```
fitform-ai/
├── main.py                  # entry point - runs the whole system
├── fitform/
│   ├── config.py            # all settings (cameras, thresholds, GPIO pins, weight...)
│   ├── camera_thread.py     # background camera capture (no lag / buffering)
│   ├── pose_engine.py       # MediaPipe Pose wrapper
│   ├── bicep_curl.py        # joint angles + rep-counting state machine
│   ├── hand_check.py        # MediaPipe Hands: fist / open palm per arm
│   ├── hand_state.py        # fist vs open classification (no camera needed)
│   ├── feedback_engine.py   # runs the rep counters and chooses the feedback text
│   ├── display_ui.py        # on-screen overlay
│   ├── gpio_feedback.py     # LEDs + buzzer (auto-disabled on a laptop)
│   ├── calorie_tracker.py   # MET-based calorie estimate
│   ├── session_summary.py   # end-of-session totals
│   └── session_logger.py    # CSV logging + Flask endpoints
├── prototypes/
│   └── bicep_curl_single_camera.py   # original single-file laptop prototype
├── docs/
│   ├── figures/             # block diagrams and figures for the logbooks/report
│   └── photos/              # progress photos
├── tests/
│   └── test_logic.py        # tests for counting, calories and logging (no camera needed)
├── logs/                    # session CSV is written here (not uploaded to GitHub)
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
Run from the project folder:
```bash
python main.py                    # default webcam
python main.py --camera 1         # use a different camera
python main.py --camera picam     # Raspberry Pi Camera Module 2 (on the Pi)
python main.py --weight 65        # your body weight in kg for calories
python main.py --video clip.mp4   # test on a recorded video
python main.py --no-gpio --no-server
```
Keys: **Q** = quit and save the session, **R** = reset counters.

Extra options: `--no-fist` turns off the clenched-fist check. Thresholds (elbow drift, wrist angle, fist rules) are in `fitform/config.py`.

### Camera set-up for reliable counting
- Stand (or sit) **2-3 m** from the camera so your **whole upper body, elbows and both hands** stay in view, including when your arm is straight down.
- Camera at about chest height. Front-on works; about 45 degrees to the side is best for seeing the elbow.
- Good, even lighting; avoid a bright window behind you.

Session log from another device on the same Wi-Fi:
- `http://<pi-ip>:5000/sessions` - JSON
- `http://<pi-ip>:5000/sessions.csv` - download CSV

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
Video frames are processed in memory and never saved or transmitted. Only exercise performance numbers are logged.
