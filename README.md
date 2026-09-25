# FitForm AI - Pose-Based Personal Trainer

Individual Major Project (6FTC2062), BEng Robotics and Artificial Intelligence, University of Hertfordshire.

FitForm AI uses a camera, MediaPipe Pose and OpenCV on a Raspberry Pi 5 to count bicep curl repetitions and check exercise form in real time. It gives feedback through an on-screen overlay, green/red LEDs and a buzzer, and logs each session to a CSV file that can be downloaded over Wi-Fi.

## Features
- Real-time pose detection (MediaPipe Pose + OpenCV)
- Strict rep counting per arm: a rep only counts if the elbow stays still and the wrist stays straight, starting from full extension
- Live feedback: "Keep elbow still!", "Straighten your wrist!", "Extend arm fully!"
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

### Raspberry Pi 5 (Raspberry Pi OS 64-bit)
```bash
python3 -m venv ~/fitform_env
source ~/fitform_env/bin/activate
pip install -r requirements.txt
```

## Usage
Run from the project folder:
```bash
python main.py                    # default webcam
python main.py --camera 1         # use a different camera
python main.py --weight 65        # your body weight in kg for calories
python main.py --video clip.mp4   # test on a recorded video
python main.py --no-gpio --no-server
```
Keys: **Q** = quit and save the session, **R** = reset counters.

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
